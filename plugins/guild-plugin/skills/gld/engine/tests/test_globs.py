"""U3 — the one path-glob dialect (globs.py)."""

import unittest

from gxengine import globs as G


class Match(unittest.TestCase):
    def yes(self, pat, *paths):
        for p in paths:
            with self.subTest(pat=pat, path=p):
                self.assertTrue(G.match(pat, p))

    def no(self, pat, *paths):
        for p in paths:
            with self.subTest(pat=pat, path=p):
                self.assertFalse(G.match(pat, p))

    def test_literal(self):
        self.yes("docs/specs/42/design.md", "docs/specs/42/design.md")
        self.no("docs/specs/42/design.md", "docs/specs/42/design.mdx", "x/docs/specs/42/design.md")

    def test_star_stays_in_one_segment(self):
        self.yes("src/*.py", "src/a.py", "src/.hidden.py")
        self.no("src/*.py", "src/a/b.py", "src/a.pyc")
        self.yes("a/*/c", "a/b/c")
        self.no("a/*/c", "a/c", "a/b/x/c")

    def test_question_mark(self):
        self.yes("a?.md", "ab.md")
        self.no("a?.md", "a.md", "abc.md", "a/.md")

    def test_leading_double_star_any_depth_including_root(self):
        self.yes("**/CLAUDE.md", "CLAUDE.md", "a/CLAUDE.md", "a/b/c/CLAUDE.md")
        self.no("**/CLAUDE.md", "xCLAUDE.md", "a/CLAUDE.md.bak")

    def test_no_implicit_basename_match(self):
        self.yes("CLAUDE.md", "CLAUDE.md")
        self.no("CLAUDE.md", "sub/CLAUDE.md")
        self.yes(".env*", ".env", ".env.local")
        self.no(".env*", "app/.env")

    def test_trailing_double_star_is_strictly_inside(self):
        self.yes(".claude/**", ".claude/settings.json", ".claude/agents/x.md")
        self.no(".claude/**", ".claude", ".claudex/a", "a/.claude/x")

    def test_middle_double_star(self):
        self.yes("a/**/b", "a/b", "a/x/b", "a/x/y/b")
        self.no("a/**/b", "a/xb", "b")

    def test_lone_double_star_and_trailing_slash(self):
        self.yes("**", "a", "a/b/c")
        self.yes("docs/", "docs/a", "docs/a/b")
        self.no("docs/", "docs")
        self.yes("**/**/x", "x", "a/x")       # `**/**` collapses

    def test_double_star_inside_a_segment_is_a_star(self):
        self.yes("a**b", "axyb")
        self.no("a**b", "ax/yb")

    def test_brackets_and_regex_chars_are_literal(self):
        self.yes("a[1].md", "a[1].md")
        self.no("a[1].md", "a1.md")
        self.yes("a+(b)|c.md", "a+(b)|c.md")
        self.no("a.md", "aXmd")

    def test_case_sensitive(self):
        self.no("src/a.py", "SRC/a.py")

    def test_match_any(self):
        self.assertEqual(G.match_any(["x/**", "**/*.md"], "a/b.md"), "**/*.md")
        self.assertIsNone(G.match_any(["x/**"], "a/b.md"))

    def test_bad_inputs_raise(self):
        for pat, path in [("/abs", "a"), ("a", "/abs"), ("a/../b", "a"), ("a", "a/../b"),
                          ("", "a"), ("a", ""), ("a//b", "a"), ("a", "a//b"), ("./a", "a"),
                          ("a", "a/"), ("docs/specs/{issue}/x", "docs/specs/1/x")]:
            with self.subTest(pat=pat, path=path):
                with self.assertRaises(ValueError):
                    G.match(pat, path)


class ControlFiles(unittest.TestCase):
    def test_control_patterns(self):
        for p in (".claude/settings.json", ".claude/agents/developer.md", "CLAUDE.md", "a/b/CLAUDE.md",
                  "x/CLAUDE.local.md", "AGENTS.md", "pkg/AGENTS.md", "docs/specs/42/procedure.yaml",
                  ".claude/guild/gates/findings.json"):  # promote: literal; rename-exception: a 0.98.7 gate record is a control file too
            with self.subTest(p=p):
                self.assertTrue(G.is_control_file(p, 42))
        for p in ("README.md", "docs/specs/43/procedure.yaml", "docs/specs/42/design.md",
                  "src/claude.py", "docs/specs/42/procedure.yaml.bak", "a/.claudex/x"):
            with self.subTest(p=p):
                self.assertFalse(G.is_control_file(p, 42))

    def test_control_is_case_insensitive(self):
        # APFS / NTFS: `.Claude/x` is the same file as `.claude/x`.
        for p in (".Claude/settings.json", "claude.md", "sub/Claude.MD", "agents.md", "Docs/Specs/42/Procedure.yaml"):
            with self.subTest(p=p):
                self.assertTrue(G.is_control_file(p, 42))

    def test_bad_issue(self):
        for bad in (0, -1, True, "42", None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    G.is_control_file("CLAUDE.md", bad)

    def test_names_control_file(self):
        self.assertTrue(G.names_control_file(".claude/agents/x.md", 7))
        self.assertTrue(G.names_control_file(".claude/agents/*.md", 7))
        self.assertTrue(G.names_control_file(".CLAUDE/**", 7))
        self.assertTrue(G.names_control_file("docs/specs/7/procedure.yaml", 7))
        self.assertTrue(G.names_control_file("docs/specs/7/*.md", 7))        # may be docs/specs/7/CLAUDE.md (P3-Z)
        self.assertFalse(G.names_control_file("docs/specs/7/design.md", 7))

    def test_names_control_file_nested_and_wildcard_folders(self):
        # P3-A: a control folder anywhere in a glob, a wildcard folder that can be `.claude`,
        # a literal control name as the last segment
        for pat in ("pkg/.claude/*.md", "**/.claude/x.md", "pkg/.CLAUDE/", ".c*/x.md", "docs/*/x.md",
                    "**/CLAUDE.md", "docs/*/AGENTS.md", "a/**/claude.local.md"):
            with self.subTest(pat=pat):
                self.assertTrue(G.names_control_file(pat, 7))
        for pat in ("release_notes/*.txt", "src/.cl/*.txt", "docs/specs/7/qa-*.md", "docs/specs/7/*.txt",
                    "docs/*.yaml", "src/*.py"):
            with self.subTest(pat=pat):
                self.assertFalse(G.names_control_file(pat, 7))

    def test_names_control_file_any_possible_overlap_is_refused(self):
        # P3-Z decision 10 (fail-closed): `**` as a folder can be `.claude`; a last segment that
        # can match a control name or folder; a trailing `**` or `/`; procedure.yaml
        for pat in ("docs/**/x.md", "**/x.txt", "docs/specs/7/*.md", "docs/*", "docs/specs/7/**", "docs/",
                    "docs/specs/7/*.yaml", "docs/AGENTS*", "a/CLAUDE.*", "a/.c*", "a/?laude.md", "src/.cl/*.md"):
            with self.subTest(pat=pat):
                self.assertTrue(G.names_control_file(pat, 7))

    def test_fold(self):
        self.assertFalse(G.match("docs/*.md", "DOCS/a.MD"))
        self.assertTrue(G.match("docs/*.md", "DOCS/a.MD", fold=True))
        self.assertEqual(G.match_any(["x/**", "**/*.md"], "A/B.MD", fold=True), "**/*.md")
        with self.assertRaises(ValueError):
            G.match("/abs", "a", fold=True)
        self.assertTrue(G.is_secret_path("App/.ENV", ["**/.env*"]))
        self.assertTrue(G.is_secret_path("keys/Server.PEM", ["**/*.pem"]))
        self.assertFalse(G.is_secret_path("src/env.py", ["**/.env*"]))


class Overlap(unittest.TestCase):
    def test_overlap(self):
        cases = [
            ("a/b.md", "a/b.md", True), ("a/b.md", "a/c.md", False),
            ("a/*.md", "a/b.md", True), ("a/*.md", "a/b.txt", False),
            ("docs/**", "docs/x/*.md", True), ("docs/**", "src/**", False),
            ("docs/*.md", "docs/*.txt", False), ("docs/a*.md", "docs/*b.md", True),
            ("docs/x*", "docs/y*", False), ("**/*.md", "docs/a.md", True),
            ("**/CLAUDE.md", "docs/specs/1/*.md", True), ("**/CLAUDE.md", "docs/specs/1/*.txt", False),
        ]
        for a, b, want in cases:
            with self.subTest(a=a, b=b):
                self.assertEqual(G.may_overlap(a, b), want)
                self.assertEqual(G.may_overlap(b, a), want)


class Covers(unittest.TestCase):
    """covers(outer, inner) — the narrowing proof of init's narrow-glob answer (A15, 2026-11-26)."""

    def test_proved(self):
        for outer, inner in (("**/*_test.dart", "test/**/*_test.dart"), ("**/*_safety_net_test.dart", "test/**/*_safety_net_test.dart"),
                             ("**", "a/b"), ("**", "a/**"), ("a/**", "a/**/b"), ("a/**", "a/b/**"), ("a/", "a/*/c"),
                             ("**/test_*.py", "crawler/**/test_*.py"), ("tests/**/*.py", "tests/unit/test_*.py"),
                             ("src/*.py", "src/a?.py"), ("src/*", "src/*.py"), ("**/x", "x"), ("**/x", "**/a/x"),
                             ("a/**/b", "a/c/**/b"), ("*a*", "xa"), ("a**b", "a*b"), ("**/**/x", "**/x")):
            with self.subTest(outer=outer, inner=inner):
                self.assertIs(G.covers(outer, inner), True)

    def test_not_proved(self):
        for outer, inner in (("test/**/*_test.dart", "**/*_test.dart"), ("a/**", "a"), ("a/**", "**/a/b"), ("src/*.py", "src/**/*.py"),
                             ("src/a?.py", "src/*.py"), ("a/*/c", "a/**/c"), ("x", "**/x"), ("tests/**/*.py", "tests/*"),
                             ("a/**/b", "a/**/c/**"), ("?", "*")):
            with self.subTest(outer=outer, inner=inner):
                self.assertIsNot(G.covers(outer, inner), True)

    def test_a_path_is_matched_exactly(self):
        self.assertIs(G.covers("lib/**", "lib/a.dart"), True)
        self.assertIs(G.covers("lib/**", "bin/a.dart"), False)

    def test_a_bad_pattern_is_an_error(self):
        for bad in ("/abs", "a/../b", "", "a//b", "x/{issue}"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                G.covers("**", bad)

    def test_a_proof_is_never_wrong(self):
        """Every proved pair, on every path of a small universe: what the inner pattern matches, the outer matches."""
        import itertools
        import random
        names = ("a", "b", "ab", "ba", "xa")
        paths = ["/".join(t) for n in range(1, 4) for t in itertools.product(names, repeat=n)]
        rnd, segs, pats = random.Random(15), ("a", "b", "ab", "*", "?", "a*", "*b", "**", "x?", "*a*"), set()
        while len(pats) < 120:
            p = "/".join(rnd.choice(segs) for _ in range(rnd.randint(1, 3)))
            try:
                G.match(p, "a")
            except ValueError:
                continue
            pats.add(p)
        hit = {p: {x for x in paths if G.match(p, x)} for p in pats}
        proved = 0
        for outer in pats:
            for inner in pats:
                if G.covers(outer, inner) is True:
                    proved += 1
                    self.assertLessEqual(hit[inner], hit[outer], (outer, inner))
        self.assertGreater(proved, 400)


if __name__ == "__main__":
    unittest.main()
