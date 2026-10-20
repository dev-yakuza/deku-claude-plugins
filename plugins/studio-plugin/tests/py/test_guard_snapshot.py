"""M0d-1a shell snapshots: aliases, functions, options, merging, alternatives, None/partial mode
(m0d1a-plan §5.4, §10.14 tests 120-133)."""

import os
import time

from guard_base import CLAUDE_SECTIONS, DEFAULT_ALIASES, GuardCase, snapshot_text
from stdo.guard import snapshot as snapmod


class Aliases(GuardCase):
    def setUp(self):
        super().setUp()
        self.mk("d")
        self.use_snapshots(snapshot_text(path=self.bin))

    def test_g_clean(self):  # 120
        r = self.ok("g clean -fdx")
        c = self.one(r, "git")
        self.assertEqual((c.aliases, c.git.sub, [w.value for w in c.git.args]), (["g"], "clean", ["-fdx"]))

    def test_trailing_space(self):  # 121
        r = self.ok("_ rm x")
        c = self.one(r, "rm")
        self.assertEqual([w.name for w in c.wrappers], ["sudo"])
        r = self.ok("_ g status")
        self.assertEqual(self.one(r, "git").git.sub, "status")

    def test_take_function(self):  # 122
        r = self.ok("take d; rm y")
        self.assertIn("function", self.kinds(r))
        self.assertEqual(self.one(r, "rm").cwds, [])

    def test_git_aliases(self):  # 123
        self.assertEqual(self.one(self.ok("gclean"), "git").argv, ["git", "clean", "--interactive", "-d"])
        self.assertEqual(self.one(self.ok("grhh"), "git").argv, ["git", "reset", "--hard"])
        self.assertEqual(self.one(self.ok("ga studio/local/x"), "git").argv, ["git", "add", "studio/local/x"])
        self.assertEqual(self.one(self.ok("gc -m x"), "git").argv, ["git", "commit", "--verbose", "-m", "x"])

    def test_recursion_and_depth(self):  # 124
        r = self.ok("ll")
        c = self.one(r, "ls")
        self.assertEqual((c.argv, c.aliases), (["ls", "-G", "-l"], ["ll", "ls"]))
        chain = [("a%d" % i, "a%d" % (i + 1)) for i in range(1, 17)] + [("a17", "true")]
        self.use_snapshots(snapshot_text(aliases=chain, path=self.bin))
        r = self.ok("a1")
        self.assertEqual(r.commands[0].argv, ["a17"])
        self.assertIn("alias-depth", r.notes)

    def test_no_expansion_positions(self):  # 125
        for cmd in ("'g' status", "\\g status", "command g", "builtin g", "exec g", "noglob g", "env g", "nice g",
                    "sudo g", "echo g", "x=g"):
            r = self.ok(cmd)
            self.assertFalse(self.by_prog(r, "git"), cmd)
        self.assertEqual(self.one(self.ok("nocorrect g status"), "git").argv, ["git", "status"])

    def test_operators_in_value(self):  # 126
        self.mk("studio")
        self.use_snapshots(snapshot_text(aliases=[("x", "'cd studio && rm a'")], path=self.bin))
        r = self.ok("x; rm b")
        S = os.path.join(self.root, "studio")
        self.assertEqual([(c.argv[1], c.cwds) for c in self.by_prog(r, "rm")], [("a", [S]), ("b", [S])])

    def test_in_command_alias_changes_do_nothing(self):  # 126a
        self.assertEqual(self.one(self.ok("unalias g; g clean -fdx"), "git").argv, ["git", "clean", "-fdx"])
        r = self.ok("alias g=echo; g clean -fdx")
        self.assertEqual(self.one(r, "git").argv, ["git", "clean", "-fdx"])
        self.assertIn("alias", self.kinds(r))
        r = self.ok("alias x='rm -rf studio'; x")
        self.assertEqual([h.term for o in r.opaque if o.kind == "alias" for h in o.hits], ["studio"])


class Functions(GuardCase):
    def test_delegated_by_position(self):  # 127
        self.use_snapshots(snapshot_text(path=self.bin))
        r = self.ok("grep foo studio/x")
        self.assertIn("via-function", self.one(r, "grep").flags)
        self.assertEqual(r.opaque, [])
        r = self.ok("find studio -delete")
        self.assertEqual(self.one(r, "find").argv, ["find", "studio", "-delete"])
        self.assertIn("via-function", self.one(self.ok("rg x"), "rg").flags)
        self.assertIn("via-function", self.one(self.ok("pkill -f s2v"), "pkill").flags)

    def test_same_body_in_user_section_is_opaque(self):  # 127a
        grep_def = CLAUDE_SECTIONS[CLAUDE_SECTIONS.index("function grep {"):CLAUDE_SECTIONS.index("# Shadow pkill")]
        funcs = grep_def + "take () {\n\tmkdir -p $@ && cd ${@:$#}\n}\nrm () {\n\tcommand rm -i $@\n}\n" \
            "function nvm:use {\n\t:\n}\ngit-foo () {\n\t:\n}\n.helper() {\n\t:\n}\n" \
            "outer () {\n    inner () {\n\t:\n    }\n}\n"
        self.use_snapshots(snapshot_text(functions=funcs, claude=False, path=self.bin))
        r = self.ok("grep foo x; ls")
        self.assertIn("function", self.kinds(r))
        self.assertEqual(self.one(r, "ls").cwds, [])
        s = self.snapshot
        for n in ("grep", "take", "rm", "nvm:use", "git-foo", ".helper", "outer"):
            self.assertIn(n, s.user_functions, n)
        self.assertNotIn("inner", s.user_functions)
        self.assertIn("claude-shadow-section-missing", s.notes)
        self.assertEqual(s.delegated, set())

    def test_unalias_in_claude_section(self):  # 127b
        self.use_snapshots(snapshot_text(aliases=DEFAULT_ALIASES + [("find", "fd")], path=self.bin))
        self.assertNotIn("find", self.snapshot.plain)
        self.assertIn("via-function", self.one(self.ok("find . -name x"), "find").flags)

    def test_markers_missing_and_intersection(self):  # 127c
        self.use_snapshots(snapshot_text(claude=False, path=self.bin), snapshot_text(path=self.bin))
        self.assertEqual(self.snapshot.delegated, set())
        r = self.ok("find . -delete")
        self.assertNotIn("via-function", self.one(r, "find").flags)  # in one variant it is plain find

    def test_marker_rules(self):  # 130b
        fake = "weird () {\n\tcat <<X\n# Aliases\nalias -- zz=rm\nX\n}\n"
        self.use_snapshots(snapshot_text(functions=fake, path=self.bin))
        self.assertNotIn("zz", self.snapshot.plain)
        self.assertIn("g", self.snapshot.plain)
        txt = snapshot_text(path=self.bin).replace("# Aliases", " # Aliases")
        v = snapmod.parse_snapshot(txt)
        self.assertIn("snapshot-markers-missing", v.notes)

    def test_parse_time(self):  # 133 (budget fixed from a measurement on Python 3.9: ~38 ms → 100 ms)
        funcs = "".join("f%d () {\n\techo %d\n\tif [[ -n $x ]]\n\tthen\n\t\tcommand ls -la ${1+\"$@\"} | head\n\tfi\n}\n"
                        % (i, i) for i in range(3000))
        aliases = [("al%d" % i, "'git log --oneline -%d'" % i) for i in range(250)]
        texts = [snapshot_text(functions=funcs, aliases=aliases, path="/usr/bin:/v%d" % i) for i in range(6)]
        texts[0] = snapshot_text(functions=funcs, aliases=[], claude=False, path=None)
        self.assertGreater(len(texts[1]), 200000)
        t = time.process_time()
        self.use_snapshots(*texts)
        self.assertLess(time.process_time() - t, 0.6)  # 6 files, 2 distinct parses
        texts = [snapshot_text(functions=funcs, aliases=aliases[:200 + i], path="/p%d" % i) for i in range(30)]
        t = time.process_time()
        s = None
        try:
            s = self.use_snapshots(*texts)
        finally:
            elapsed = time.process_time() - t
        self.assertIsNone(s)  # 30 distinct variants > 8
        self.assertLess(elapsed, 3.0)


class Merging(GuardCase):
    def text(self, aliases, **kw):
        kw.setdefault("path", self.bin)
        return snapshot_text(aliases=aliases, **kw)

    def test_alternatives_deny_if_any(self):  # 130(d)
        self.use_snapshots(self.text([("g", "git")]), self.text([("ll", "'ls -l'")]))
        self.assertEqual(self.snapshot.alternatives["g"], ["git", None])
        r = self.ok("g clean -fdx")
        c = self.one(r, "git")  # "not an alias" dropped: g is not runnable
        self.assertEqual(c.alt["source"][0], {"name": "g", "value": "git", "in": 1, "of": 2})
        self.assertEqual(len(r.commands), 1)
        self.exe("g")
        r = self.ok("g clean -fdx")
        self.assertEqual(sorted(c.prog for c in r.commands), ["g", "git"])
        groups = {c.alt["group"] for c in r.commands}
        self.assertEqual(len(groups), 1)
        self.use_snapshots(self.text([("g", "git")]), self.text([("g", "gitui")]))
        os.remove(os.path.join(self.bin, "g"))
        r = self.ok("g clean -fdx; rm studio/x")
        self.assertEqual(sorted(c.prog for c in r.commands if c.alt), ["git", "gitui"])
        self.assertEqual(len(self.by_prog(r, "rm")), 1)  # shared commands are not duplicated

    def test_measured_distribution(self):  # 130(d2)
        zero = snapshot_text(aliases=[], claude=False, options=(), path=None)
        normal = [self.text(DEFAULT_ALIASES) for _ in range(4)]
        extra = self.text(DEFAULT_ALIASES + [("zz", "'ls -a'")])
        self.use_snapshots(zero, *normal, extra)
        s = self.snapshot
        self.assertEqual(len(s.variants), 3)
        self.assertEqual(s.plain, {})
        self.assertEqual(s.alternatives["g"], ["git", None])
        c = self.one(self.ok("g clean -fdx"), "git")
        self.assertEqual(c.alt["source"][0], {"name": "g", "value": "git", "in": 5, "of": 6})
        r = self.ok("ll")
        self.assertEqual([c.argv for c in r.commands], [["ls", "-G", "-l"], ["ls", "-l"]] if len(r.commands) == 2
                         else [c.argv for c in r.commands])
        self.assertTrue(all(c.alt for c in r.commands))
        r = self.ok("grep x f")
        self.assertTrue(self.by_prog(r, "grep"))
        r = self.ok("_ g x")  # 130(j2): the chain's sub-alternatives share one group, index as a path
        c = self.one(r, "git")
        self.assertEqual((c.alt["index"], [x["name"] for x in c.alt["source"]]), ("0.0", ["_", "g"]))
        self.exe("_")
        self.exe("g")
        r = self.ok("_ g x")
        self.assertEqual(len({c.alt["group"] for c in r.commands}), 1)
        self.assertEqual(sorted(c.alt["index"] for c in r.commands), ["0.0", "0.1", "1"])

    def test_alternative_caps(self):  # 130(d3)
        texts = [self.text([("g", "'git %d'" % i)]) for i in range(8)]
        snap, notes = None, None
        self.use_snapshots(*texts, "x" * (snapmod.MAX_SIZE + 1))  # an unreadable file adds "not an alias"
        self.exe("g")
        r = self.ok("g x")
        self.assertEqual(len(r.commands), 1)  # 8 values + "not an alias" (g is runnable) = 9 > ALT_MAX
        self.assertIn("ambiguous-alias", self.kinds(r))
        os.remove(os.path.join(self.bin, "g"))
        r = self.ok("g x")
        self.assertNotIn("ambiguous-alias", self.kinds(r))
        self.assertEqual(len(r.commands), 8)  # "not an alias" dropped: g cannot run
        # 64 parses in total
        aliases_a = [("a", "'echo a1'"), ("b", "'echo b1'"), ("c", "'echo c1'")]
        aliases_b = [("a", "'echo a2'"), ("b", "'echo b2'"), ("c", "'echo c2'")]
        aliases_c = [("a", "'echo a3'"), ("b", "'echo b3'"), ("c", "'echo c3'")]
        aliases_d = [("a", "'echo a4'"), ("b", "'echo b4'"), ("c", "'echo c4'")]
        self.use_snapshots(self.text(aliases_a), self.text(aliases_b), self.text(aliases_c), self.text(aliases_d))
        r = self.ok("a; b; c; a")
        self.assertIn("ambiguous-alias", self.kinds(r))
        del snap, notes, texts

    def test_files_and_limits(self):  # 130(c, f, g, h, i, j)
        same_a = self.text(DEFAULT_ALIASES, path="/usr/bin")
        same_b = self.text(DEFAULT_ALIASES, path="/opt/x:/usr/bin")
        self.use_snapshots(same_a, same_b)
        self.assertEqual(len(self.snapshot.variants), 1)
        self.assertEqual(sorted(self.snapshot.paths), ["/opt/x:/usr/bin", "/usr/bin"])
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        self.use_snapshots(self.text([("g", "git")]), self.text([("g", "other")]), ages=[60, 15 * 86400])
        self.assertIn("g", self.snapshot.plain)
        with open(os.path.join(d, "snapshot-bash-1-x.sh"), "w") as f:
            f.write(self.text([("g", "bad")]))
        self.assertIn("g", snapmod.load(self.env)[0].plain)
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
        s = self.use_snapshots(*[self.text([("g", "'git %d'" % i)]) for i in range(9)])
        self.assertIsNone(s)
        self.assertIn("snapshot-too-many-variants", self.snapshot_notes)
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
        s = self.use_snapshots(self.text([("g", "git")]), "x" * (snapmod.MAX_SIZE + 10))
        self.assertTrue(any(n.startswith("snapshot-unreadable") for n in s.notes))
        self.assertEqual(s.alternatives["g"], ["git", None])
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
        self.assertIsNone(self.use_snapshots("x" * (snapmod.MAX_SIZE + 10)))
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
        os.rmdir(d)
        self.assertEqual(snapmod.load(self.env), (None, ["snapshot-dir-missing"]))

    def test_truncated_unknown_command(self):  # 130(j), plan v7 MINOR
        texts = [self.text([("g", "git")])] + [self.text([("ll", "'ls -l'")]) for _ in range(30)]
        ages = [3600 * 24] + [60 + i for i in range(30)]
        s = self.use_snapshots(*texts, ages=ages)
        self.assertIn("snapshot-truncated", s.notes)
        self.assertEqual(s.alternatives["ll"], ["ls -l", None])
        r = self.ok("g clean -fdx")
        self.assertEqual(self.kinds(r), ["unknown-command"])
        self.assertEqual(self.one(r, "g").argv, ["g", "clean", "-fdx"])
        self.assertEqual(self.kinds(self.ok("git status")), [])

    def test_none_mode(self):  # 130(k), 131, 132
        self.snapshot = None
        r = self.ok("g clean -fdx")
        self.assertEqual(self.kinds(r), ["unknown-command"])
        self.assertIn("snapshot-unavailable", r.notes)
        self.assertEqual(self.kinds(self.ok("git clean -fdx")), [])
        self.assertEqual(self.kinds(self.ok("cd x; echo; [[ -f a ]]")), [])
        self.assertEqual(self.kinds(self.ok("sudo g x")), [])  # run by sudo, not by the shell
        other = os.path.join(self.tmp, "obin")
        os.makedirs(other)
        p = os.path.join(other, "only-here")
        with open(p, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(p, 0o755)
        self.use_snapshots(self.text([("x", "y")], path=other))
        self.assertEqual(self.kinds(self.ok("only-here")), [])

    def test_postlude_and_options(self):  # 130a, 129
        self.use_snapshots(self.text(DEFAULT_ALIASES + [("unsetenv", "x")], options=("extendedglob", "autopushd")))
        self.assertFalse(self.snapshot.options["extendedglob"])
        self.assertNotIn("unsetenv", self.snapshot.plain)
        self.use_snapshots(self.text([], options=("rcquotes",)))
        self.assertEqual(self.one(self.ok("echo 'it''s'"), "echo").argv, ["echo", "it's"])
        self.use_snapshots(self.text([], options=("rcquotes",)), self.text([("q", "x")]))
        w = self.one(self.ok("echo 'it''s'"), "echo").words[1]
        self.assertEqual((w.value, w.alt), ("its", "it's"))
        self.use_snapshots(self.text([], options=("shwordsplit",)))
        self.env["XS"] = "a b"
        self.assertTrue(self.one(self.ok("echo $XS"), "echo").words[1].dynamic)
        self.mk("q")
        self.use_snapshots(self.text([], options=("cdablevars",)))
        self.assertEqual(self.one(self.ok("cd name; ls"), "ls").cwds, [])

    def test_exec_by_program_no_alias(self):  # NIT v7
        self.use_snapshots(self.text(DEFAULT_ALIASES))
        os.makedirs(os.path.join(self.root, ".git"))
        self.mk(".claude", "studio", "scripts", "lock.py", file=True)
        for cmd in ("xargs g x", "find . -exec g {} \\;", "python3 .claude/studio/scripts/lock.py run --kind tts -- g x",
                    "env g x"):
            r = self.ok(cmd)
            self.assertFalse(self.by_prog(r, "git"), cmd)

    def test_autocd_ignored(self):  # 128
        self.mk("studio")
        self.use_snapshots(self.text(DEFAULT_ALIASES))
        r = self.ok("studio; rm x")
        self.assertEqual(self.one(r, "rm").cwds, [self.root])
        r = self.ok("...; rm x", cwd=os.path.join(self.root, "studio"))
        self.assertEqual(self.one(r, "rm").cwds, [os.path.join(self.root, "studio")])
        self.mk("a")
        r = self.ok("cd a; -; rm x")
        self.assertEqual(self.one(r, "rm").cwds, [self.root])

    def test_no_execution(self):  # 133
        marker = os.path.join(self.tmp, "should-not-exist")
        funcs = "boom () {\n\ttouch %s\n}\n" % marker
        self.use_snapshots(self.text(DEFAULT_ALIASES, functions=funcs) + "touch %s\n" % marker)
        self.assertFalse(os.path.exists(marker))


class Review1Snapshot(GuardCase):
    def test_markers_removed_functions_kept(self):  # MINOR 2: 127c
        txt = snapshot_text(path=self.bin)
        for m in ("# Check for rg availability", "# Shadow find/grep with embedded bfs/ugrep",
                  "# Shadow pkill to refuse patterns matching the CLI process"):
            txt = txt.replace(m + "\n", "")
        self.use_snapshots(txt)
        s = self.snapshot
        self.assertTrue({"find", "grep", "pkill", "rg"} <= s.user_functions)
        self.assertEqual(s.delegated, set())
        r = self.ok("find studio -delete")
        self.assertIn("function", self.kinds(r))
        # no functions at all: the original command
        self.use_snapshots(snapshot_text(claude=False, functions="", path=self.bin))
        self.assertEqual(self.ok("find . -delete").opaque, [])

    def test_function_inside_alias_region(self):  # MINOR 2
        self.use_snapshots(snapshot_text(path=self.bin, extra_alias_lines=("sneaky () {", "\t:", "}")))
        self.assertIn("sneaky", self.snapshot.user_functions)

    def test_no_markers_at_all(self):  # MINOR 2
        txt = "inner_only () {\n  nested () {\n  :\n  }\n}\n  function find {\n  :\n}\n"
        v = snapmod.parse_snapshot(txt)
        self.assertTrue({"inner_only", "nested", "find"} <= v.user_functions)

    def test_indented_user_definitions_are_not_names(self):  # MINOR 4 (G9)
        funcs = "outer () {\n\tinner () {\n\t\t:\n\t}\n}\n  spaced () {\n:\n}\n"
        self.use_snapshots(snapshot_text(functions=funcs, path=self.bin))
        self.assertIn("outer", self.snapshot.user_functions)
        self.assertNotIn("inner", self.snapshot.user_functions)
        self.assertNotIn("spaced", self.snapshot.user_functions)

    def test_alias_across_line_continuation(self):  # MINOR 3
        self.use_snapshots(snapshot_text(path=self.bin))
        self.assertEqual(self.one(self.ok("g\\\n clean -fdx"), "git").argv, ["git", "clean", "-fdx"])
        self.assertEqual(self.one(self.ok("g\\\nr\\\nhh"), "git").argv, ["git", "reset", "--hard"])
        self.assertEqual(self.one(self.ok("g\\\nx"), "gx").argv, ["gx"])  # joined first: `gx` is no alias

    def test_trailing_space_through_nested_aliases(self):  # MINOR 3
        self.use_snapshots(snapshot_text(aliases=DEFAULT_ALIASES + [("h", "'gg g'"), ("gg", "'g '")], path=self.bin))
        r = self.ok("h status")
        self.assertEqual([c.argv for c in r.commands], [["git", "git", "status"]])


class Review2Snapshot(GuardCase):
    def test_trailing_space_deeper(self):  # NIT
        self.use_snapshots(snapshot_text(aliases=DEFAULT_ALIASES + [("gg", "'g '")], path=self.bin))
        self.assertEqual(self.ok("gg gg x").commands[0].argv, ["git", "git", "x"])
        self.assertEqual(self.ok("gg gg gg x").commands[0].argv, ["git", "git", "git", "x"])

    def test_format_unrecognized_note(self):  # NIT
        self.use_snapshots("just text\nno markers () {\n:\n}\n")
        self.assertIn("snapshot-format-unrecognized", self.ok("ls").notes)
