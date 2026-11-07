"""Pilot 2 guard fixes (0.0.25, fix-0025-plan §1, §2): P11 — sed by an allowlist of shapes (sedshape), the sed holes
of 0.0.24 at the root and under studio/videos/v, a sed outside a Studio repository by its path pieces; P14/P15 — a
refusal's closing line: the non-stop suffix (sed, interpreter file work), the G-EVIDENCE classes by NoEvidence code,
INV9 for everything else and for a call with different suffixes. Real git only in temporary repositories."""

import json
import os
import re
import subprocess
import sys
import unittest

import helpers
import state_fixtures as F
import test_guard_commit
import transcripts as TR
from commit_base import SID, CommitCase
from stdo.guard import approve, judge, messages, sedshape, transcript
from stdo.guard.messages import INV9, LABEL, NONSTOP, REASK, Deny
from stdo.guard.model import Word
from test_guard_judge import JudgeCase, runner_deny, sed_deny

GUARD_DIR = os.path.join(helpers.SCRIPTS, "stdo", "guard")


def W(*values):
    """Literal words; "" is written '' in the source (Word.lit("") would be an expansion that came out empty)."""
    return [Word("''", "", quoted=True) if v == "" else Word.lit(v) for v in values]


def shape(*values, exec_by=None):
    return sedshape.classify(W(*values), exec_by)[0]


def glob(value, base):
    return Word(value, value, glob=True, glob_base=base)


# ---------------------------------------------------------------- sedshape (§1.1–§1.3)

class SedShape(unittest.TestCase):
    READ = [("-n", "1,80p", "f"), ("-n", "/def /p", "f"), ("-n", "/^## A/,/^## /p", "f"), ("-n", "/a/I,/b/Ip", "f"),
            ("-n", "/a/I!p", "f"), ("-n", "01,3p", "f"), ("-n", "$=", "f"), ("1d;3q", "f"), ("-n", "/x/{p;q;}", "f"),
            ("-E", "-n", "s/a/b/p", "f"), ("-nE", "p", "f"), ("-u", "-r", "p", "f"), ("p;", "f"), ("n;d", "f"),
            ("-n", "2,$p", "f"), ("-n", "2,/x/p", "f"), ("-n", "/a/,3p", "f"), ("-n", "/a/,$p", "f"),
            ("-n", "$!p", "f"), ("-n", "1{/a/{p;};}", "f"), ("-n", "1{p;};2p", "f"), ("s/a/&&&/", "f"),
            ("s/\\(a\\)/\\1x/g", "f"), ("-n", "s/a/b/2p", "f"), ("s/a/b/gpI", "f"), ("s/a b/c d/", "f"),
            ("s/a\\/b/c/", "f"), ("s/a/\\&\\&\\&\\&/", "f"), ("p",), ("--version",), ("--help",)]
    OTHER = [
        # options: -e -f -l -I -s -z, long options, clusters with other letters
        ("-e", "p", "f"), ("-ne", "p", "f"), ("-nf", "x"), ("-fevil.sed",), ("--expression=p", "f"), ("--in-place=x",),
        ("-l", "5", "p"), ("-I", "p", "f"), ("-s", "p", "f"), ("-z", "p", "f"), ("--", "p", "f"), ("--debug", "p"),
        ("--version", "f"), ("-x", "p"),
        # in place: only -i '' and -i.bak; no -n; once
        ("-i", "x", "1w P", "a"), ("-i.json", "s/a/b/", "st"), ("-i.orig", "s/a/b/", "f"), ("-Ei", "", "p", "f"),
        ("-iE", "p", "f"), ("-n", "-i", "", "p", "f"), ("-i", "", "-i", "", "p", "f"), ("-i",),
        ("-i", "", "-n", "p", "f"),
        # the script is the first operand; no option after it
        ("s/a/b/", "P", "-i"), ("-n", "1w P", "-e", "p", "a"), ("p", "-"), ("p", "f", "-n"), (),
        # commands outside p = d q n s
        ("s/a/b/e", "f"), ("1e ls", "f"), ("1w x", "f"), ("1r x", "f"), ("1R x", "f"), ("1W x", "f"),
        ("s/a/b/w x", "f"),
        ("a\\x", "f"), ("1i x", "f"), ("c x", "f"), ("y/a/b/", "f"), ("G;h;G;h;$p", "f"), ("x", "f"), ("H", "f"),
        ("l", "f"), ("L", "f"), ("F", "f"), ("z", "f"), ("v", "f"), ("b", "f"), ("t", "f"), ("T", "f"), (":a", "f"),
        ("D", "f"), ("N", "f"), ("P", "f"), ("#n", "f"), ("q5", "f"), ("Q", "f"), ("s/a/b/m", "f"), ("s/a/b/M", "f"),
        # addresses
        ("-n", "0,/b/p"), ("-n", "00,/b/p"), ("-n", "0p"), ("-n", "1,+2p"), ("-n", "0~3p"), ("-n", "1~2p"),
        ("-n", "1!!p"), ("-n", "!p"), ("-n", "$,3p"), ("-n", "\\%a%p"), ("-n", "1,3="), ("1,3q",),
        # delimiters other than /, whitespace outside a regex, more than one line
        ("s|a|b|",), ("s#a#b#g",), ("-n", "1 p"), ("-n", "/x/I p"), ("p\np",), ("p; p",),
        # blocks BSD reads otherwise
        ("-n", "/x/{p}"), ("-n", "/a/{p;q}"), ("-n", "1{p;}2p"), ("{}",), ("-n", "{;}"),
        # [ anywhere (GNU and BSD bracket expressions differ)
        ("s/[/]/;a\\x",), ("s/[]/]/;/w D/p",), ("s/[[:alpha:]/]/;/w D/q",), ("s/[^]/]/;/w D/x",), ("s/\\[/x/",),
        ("-n", "/[a]/p"),
        # size and growth
        ("p;" * 101,), (";".join(["s/.*/&&/"] * 4),), (";".join(["s/\\(.*\\)/\\1\\1/"] * 4),), ("s/a/\\0/",),
        ("s/a/&&/;s/b/\\1\\2/",)]

    def test_read_shapes(self):
        for args in self.READ:
            self.assertEqual(shape(*args), "read", args)

    def test_other_shapes(self):
        for args in self.OTHER:
            self.assertEqual(shape(*args), "other", args)

    def test_edit_shapes_and_targets(self):
        k, det = sedshape.classify(W("-i", "", "s/a/b/", "x.ts", "y.ts"))
        self.assertEqual(k, "edit")
        self.assertEqual([v for _w, v in sedshape.targets(det)], ["x.ts", "y.ts", "s/a/b/"])  # GNU: the script word
        k, det = sedshape.classify(W("-E", "-i.bak", "s/a/b/g", "x.ts"))
        self.assertEqual(k, "edit")
        self.assertEqual([v for _w, v in sedshape.targets(det)], ["x.ts", "x.ts.bak", "s/a/b/g"])
        self.assertEqual(shape("-i", "", "-E", "1d", "f"), "edit")

    def test_empty_words_only_as_written(self):
        for raw in ("''", '""', "$''", '"$X"', "''''", "\"\"''"):  # a quoted part and nothing unquoted: kept
            self.assertEqual(sedshape.classify([Word.lit("-i"), Word(raw, "", quoted=True), Word.lit("s/a/b/"),
                                                Word.lit("f")])[0], "edit", raw)
        # an unquoted expansion that is empty: the shell drops the word
        for raw in ("$X", "${X}", "$Y", "", '$X""', "`x`"):
            self.assertEqual(sedshape.classify([Word.lit("-i"), Word(raw, "", quoted=True), Word.lit("p"),
                                                Word.lit("1w P"), Word.lit("a")])[0], "other", raw)
            self.assertEqual(sedshape.classify([Word(raw, "", quoted=True), Word.lit("-n"), Word.lit("p"),
                                                Word.lit("f")])[0], "other", raw)
            self.assertEqual(sedshape.classify([Word.lit("-n"), Word.lit("p"), Word(raw, "", quoted=True)])[0],
                             "other", raw)

    def test_edit_globs(self):
        # judge_glob checks one folder: an edit of a glob is refused (`.claude/*/config.json`)
        for g, base in (("*.ts", ""), ("src/*.ts", "src/"), (".claude/*/config.json", ".claude/")):
            self.assertEqual(sedshape.classify(W("-i", "", "s/a/b/") + [glob(g, base)])[0], "other", g)
        self.assertEqual(sedshape.classify(W("-n", "p") + [glob("src/*.ts", "src/")])[0], "read")

    def test_growth_cap(self):
        self.assertEqual(shape(";".join(["s/a/&/"] * 3)), "read")
        self.assertEqual(shape(";".join(["s/a/&/"] * 4)), "other")
        self.assertEqual(shape("s/a/\\&&\\&/"), "read")  # \& is a literal &
        self.assertEqual(shape("s/\\(a\\)/&\\1\\9/"), "read")
        self.assertEqual(shape("s/\\(a\\)/&\\1\\9&/"), "other")
        self.assertEqual(shape("/&&&&/p"), "read")  # & in a regex is not growth

    def test_script_size(self):
        self.assertEqual(shape("-n", "s/" + "a" * 196 + "//"), "read")  # 200 characters
        self.assertEqual(shape("-n", "s/" + "a" * 197 + "//"), "other")  # 201

    def test_dynamic_and_glob_words(self):
        dyn = Word("$N", None, dynamic=True, dyn=["param:N"], skeleton="\0")
        self.assertEqual(sedshape.classify([Word.lit("-n"), dyn, Word.lit("f")])[0], "other")
        self.assertEqual(sedshape.classify([Word.lit("p"), dyn])[0], "other")
        self.assertEqual(sedshape.classify([Word.lit("-n"), glob("s/a*/b/", "")])[0], "other")  # an unquoted script
        self.assertEqual(sedshape.classify([Word.lit("-n"), Word.lit("p"), glob("*", "")])[0], "other")
        self.assertEqual(sedshape.classify([Word.lit("-n"), Word.lit("p"), glob("*.md", "")])[0], "other")
        self.assertEqual(sedshape.classify([Word.lit("-n"), Word.lit("p"), glob("dir/*.md", "dir/")])[0], "read")
        self.assertEqual(sedshape.classify([Word.lit("-n"), Word.lit("p"), glob("./*", "./")])[0], "read")
        self.assertEqual(sedshape.classify([Word.lit("-n"), Word.lit("p"), glob("a*.md", "")])[0], "read")
        self.assertEqual(sedshape.classify([Word.lit("-n"), Word.lit("p"), glob("f*(e:x:)", "")])[0], "other")

    def test_find_and_xargs_templates(self):
        found = Word("{}", None, dynamic=True, dyn=["find-path"], skeleton="\0")
        fed = Word("{}", None, dynamic=True, dyn=["xargs-input"], skeleton="\0")
        self.assertEqual(sedshape.classify(W("-n", "p") + [found], "find")[0], "read")
        self.assertEqual(sedshape.classify(W("-i", "", "s/a/b/") + [found], "find")[0], "other")  # edit under find
        self.assertEqual(sedshape.classify(W("-n") + [found, Word.lit("g")], "find")[0], "other")  # '{}' as script
        self.assertEqual(sedshape.classify(W("-n", "p", "x{}"), "find")[0], "other")
        self.assertEqual(sedshape.classify(W("-n", "s/{}/x/p", "f"), "find")[0], "other")
        self.assertEqual(sedshape.classify(W("-n", "s/{}/x/p", "f"))[0], "read")  # not under find: a literal
        self.assertEqual(sedshape.classify(W("-n", "p") + [found])[0], "other")  # find-path outside find: dynamic
        self.assertEqual(sedshape.classify(W("-n", "p") + [fed], "xargs")[0], "other")
        self.assertEqual(sedshape.classify(W("-n", "p", "f"), "xargs")[0], "other")

    def test_pieces(self):
        got = sedshape.pieces(W("-n", "1w /abs/x", "1w/abs/y", "s/a/b/w/abs/z", "/a/w/abs/q", "1{w/abs/r\n}",
                                "1wname", "s/config.json/settings.json/"))
        for want in ("/abs/x", "/abs/y", "/abs/z", "/abs/q", "/abs/r", "name"):
            self.assertIn(want, got)
        self.assertIn("s/config.json/settings.json/", got)  # holds /: resolved, lands nowhere
        self.assertNotIn("-n", got)
        self.assertEqual(len(got), len(set(got)))
        self.assertIn("/b/w/abs/z", sedshape.pieces(W("s/r/b/w/abs/z")))  # every w/r letter, overlapping
        self.assertIn("/abs/z", sedshape.pieces(W("s/r/b/w/abs/z")))


# ---------------------------------------------------------------- sed through the judge (§1.4)

class SedJudge(JudgeCase):
    def setUp(self):
        super().setUp()
        self.vdir = os.path.join(self.repo, "studio", "videos", "v")
        self.out = os.path.join(self.tmp, "elsewhere")
        os.makedirs(self.out)

    def test_holes_under_the_video_folder(self):
        for mode in ("with", "none"):
            self.mode = mode
            for cmd, rule in sed_deny("../../../", ""):
                d = self.assertDeny(cmd, cwd=self.vdir)
                if rule == "G-OPAQUE" and not cmd.startswith("find"):
                    self.assertEqual(d.rule, rule, "%s: %s" % (cmd, d.message()))

    def test_runners_under_the_video_folder(self):  # G1 §5: RUNNER_DENY formatted like sed_deny
        for mode in ("with", "none"):
            self.mode = mode
            for cmd, _rule in runner_deny("../../../"):
                self.assertDeny(cmd, cwd=self.vdir)

    def test_still_denied(self):
        self.assertDeny("sed -i '' s/a/b/ .claude/studio/config.json", "G-PROT")
        self.assertDeny("sed -i.bak s/a/b/ studio/videos/v/work/state.json", "G-PROT")
        self.assertDeny("sed -i '' s/a/b/ studio/CREDITS.yaml", "G-PROT")
        st = self.env["S2V_STATE_DIR"]
        os.makedirs(os.path.join(st, "heavy.lock.d"), exist_ok=True)
        self.assertDeny("sed -n p %s/heavy.lock.d/owner.json" % st, "G-OUT")
        self.assertDeny("sed -n p studio/cast/a/character/.work/op.lock.d/owner.json", "G-OUT")
        hook = self.hook("Bash", {"command": "sed -n 1,80p a.txt"})
        hook.update({"agent_id": "a1", "agent_type": "std-auditor"})
        deny, _ctx = judge.decide(hook, self.env, snapshot_loader=self.loader)
        self.assertEqual(deny and deny.rule, "G-AUDIT")

    def test_backup_is_judged_as_a_write(self):
        # -i.bak writes <file>.bak: every target goes through check_target as a write
        seen = []
        real = judge.check_target

        def spy(ctx, cmd, word, value, op, *a, **k):
            seen.append((value, op))
            return real(ctx, cmd, word, value, op, *a, **k)
        judge.check_target = spy
        try:
            self.assertPass("sed -i.bak s/a/b/ src/x.ts")
        finally:
            judge.check_target = real
        for v in ("src/x.ts", "src/x.ts.bak", "s/a/b/"):
            self.assertIn((v, "write"), seen)
        self.assertDeny("sed -i.bak s/a/b/ studio/videos/v/work/state.json", "G-PROT")
        self.assertDeny("sed -i.bak s/a/b/ studio/videos/v/work/checks/x", "G-PROT")  # the backup is there too

    def test_only_the_system_sed(self):
        # a sed elsewhere, or a bare sed with PATH changed, may not be the system's: never shaped (other)
        for cmd in ("/tmp/sed -n p studio/videos/v/work/state.json", "./sed -n p studio/videos/v/work/state.json",
                    "PATH=src:$PATH sed -n p studio/videos/v/work/state.json",
                    "export PATH=src:$PATH; sed -n p studio/videos/v/work/state.json", "env -i sed -n p a.txt",
                    "env -u PATH sed -n p a.txt"):
            d = self.assertDeny(cmd, "G-OPAQUE")
            self.assertTrue(d.message().endswith("\n" + NONSTOP), cmd)
        # a system bin path is trusted whatever PATH is: the shape decides
        for cmd in ("/usr/bin/sed -n p studio/videos/v/work/state.json", "env -i /usr/bin/sed -n p a.txt",
                    "PATH=/tmp /usr/bin/sed -n p a.txt"):
            self.assertPass(cmd)
        self.assertPass('X=; sed -i "$X" s/a/b/ src/x.ts')  # quoted: the shell keeps the empty suffix
        self.assertDeny("X=; sed -i $X s/a/b/ src/x.ts", "G-OPAQUE")

    def test_is_writer_after_a_bulk_writer(self):
        # W4: after an extraction in a Studio repository a reading sed passes, an editing one does not
        self.assertPass("tar -xf a.tar -C dist && sed -n p dist/a.txt")
        self.assertDeny("tar -xf a.tar -C dist && sed -i '' s/a/b/ dist/a.txt", "G-PROT")

    def test_outside_a_studio_repository(self):
        repo, parent = self.repo, os.path.dirname(self.repo)
        st = self.env["S2V_STATE_DIR"]
        deny = ["cd /tmp && sed -n '1w %s/.claude/studio/config.json' x" % repo,
                "cd /tmp && sed -n '1w%s/studio/x' x" % repo,
                "sed 's/a/b/w ../%s/studio/videos/v/work/state.json' x" % os.path.basename(repo),
                "sed -n \"1w $S2V_STATE_DIR/heavy.lock.d/owner.json\" x",
                "sed -n '1w %s/heavy.lock.d/owner.json' x" % st,
                "sed -i x '1w %s/studio/videos/v/work/state.json' a.txt" % repo,
                "sed 's/a/b/w%s/studio/x' x" % repo, "sed -n '/a/w%s/studio/x' x" % repo,
                "sed -n '1{w%s/studio/x\n}' x" % repo, "sed '1r %s/heavy.lock.d/owner.json' x" % st,
                "cd %s && sed -n '1w %s/.claude/studio/config.json' x" % (parent, os.path.basename(repo)),
                "echo x | xargs sed -n '1w %s/studio/x'" % repo,
                "X=; sed -i $X p '1w %s/.claude/studio/config.json' a.txt" % repo,
                "X=''; sed -i $X p '1w %s/studio/x' a.txt" % repo,
                "PATH=/usr/bin sed -n '1w %s/.claude/studio/config.json' a.txt" % repo,
                "PATH=/usr/bin:/bin sed 's/a/b/w %s/studio/x' a.txt" % repo,
                "env -i sed -n '1w %s/studio/x' a.txt" % repo, "env -i /usr/bin/sed -n '1w %s/studio/x' a.txt" % repo,
                "env -u PATH /usr/bin/sed -n '1w %s/studio/x' a.txt" % repo,
                "export PATH=/usr/bin; sed -n '1w %s/studio/x' a.txt" % repo,
                "/tmp/sed -n '1w %s/studio/x' a.txt" % repo]
        for cmd in deny:
            d = self.assertDeny(cmd, "G-OPAQUE", cwd=self.out)
            self.assertTrue(d.message().endswith("\n" + NONSTOP), cmd)
        for cmd in ("sed -n p x", "sed -i 's/Studio/IDE/g' README.md", "sed 's/config.json/settings.json/' f",
                    "sed -n '1w /tmp/elsewhere/x' f", "sed -i x 's/a/b/' f", "sed 's/a/b/e' f",
                    "sed -n 1,80p %s/studio/videos/v/work/state.json" % repo, "X=; sed -i $X s/a/b/ f",
                    "sed -i '' s/a/b/ %s/src/x.ts" % repo):
            self.assertPass(cmd, cwd=self.out)
        # an edit or a write role outside still meets the protected files the words name
        self.assertDeny("sed -i '' s/a/b/ %s/studio/videos/v/work/state.json" % repo, "G-PROT", cwd=self.out)

    def test_outside_candidate_cap(self):
        script = ";".join("1w d/%d" % i for i in range(judge.MAX_CANDIDATES + 1))
        self.assertDeny("sed -n '%s' x" % script, "G-LIMIT", cwd=self.out)

    def test_package_runners_are_not_sed(self):
        self.assertDeny("npx sed -n p studio/videos/v/work/state.json", "G-PROT")
        self.assertDeny("bunx sed -n p studio/videos/v/work/state.json", "G-PROT")


# ---------------------------------------------------------------- closing lines (§2)

class Suffixes(JudgeCase):
    def test_texts(self):
        self.assertEqual(NONSTOP, "This is not a stop: read a file with the Read tool (offset/limit for a line range) "
                                  "and write or change it with Write or Edit — the guard checks those.")
        first = "Stop: do not reach the same effect another way (INV9)."
        self.assertTrue(INV9.startswith(first + " "))
        self.assertEqual(REASK, first + " If the person has already answered, show the question again as the stage "
                                        "says and run the command alone as your next tool call.")
        self.assertEqual(LABEL, first + " The answer does not match this option exactly: if the person chose another "
                                        "option, follow it; if the option you showed was spelled differently, ask "
                                        "again with the label the stage gives.")

    def test_message_rules(self):
        a = Deny("G-OPAQUE", "a", suffix=NONSTOP)
        b = Deny("G-OPAQUE", "b", suffix=NONSTOP)
        c = Deny("G-PROT", "c")
        self.assertTrue(a.message().endswith("\n" + NONSTOP))
        self.assertTrue(a.message([a]).endswith("\n" + NONSTOP))
        m = a.message([a, b])
        self.assertTrue(m.endswith("\n" + NONSTOP))
        self.assertIn(" (and 1 more)", m)
        m = a.message([a, b, c])
        self.assertTrue(m.endswith("\n" + INV9))
        self.assertIn(" (and 2 more)", m)
        self.assertTrue(c.message([c, a]).endswith("\n" + INV9))
        self.assertTrue(Deny("G-EVIDENCE", "x", suffix=REASK).message([Deny("G-X", "y", suffix=LABEL)])
                        .endswith("\n" + INV9))
        long = Deny("G-OPAQUE", "x" * 3000, suffix=LABEL).message()
        self.assertLessEqual(len(long), messages.LIMIT)
        self.assertTrue(long.endswith(" ...\n" + LABEL))

    def test_sed_other_is_not_a_stop(self):
        d = self.assertDeny("sed -n '1w x' a.txt", "G-OPAQUE")
        self.assertTrue(d.message().endswith("\n" + NONSTOP))
        _deny, ctx = judge.decide(self.hook("Bash", {"command": "sed x a.txt; sed 's/a/b/e' a.txt"}), self.env,
                                  snapshot_loader=self.loader)
        m = ctx.denies[0].message(ctx.denies)
        self.assertIn("(and 1 more)", m)
        self.assertTrue(m.endswith("\n" + NONSTOP))

    def test_a_different_deny_in_the_call_keeps_inv9(self):
        _deny, ctx = judge.decide(self.hook("Bash", {"command": "sed x a.txt; rm -rf studio/local"}), self.env,
                                  snapshot_loader=self.loader)
        self.assertEqual([d.rule for d in ctx.denies], ["G-OPAQUE", "G-DEL"])
        m = ctx.denies[0].message(ctx.denies)
        self.assertIn("(and 1 more)", m)
        self.assertTrue(m.endswith("\n" + INV9))

    def test_interpreters(self):
        nonstop = ["python3 -c \"open('studio/videos/v/work/state.json', 'w')\"",
                   "python3 -c \"print(open('studio/videos/v/script.md').read())\"",
                   "python3 - <<'EOF'\nopen('studio/videos/v/work/state.json','w')\nEOF",
                   "python3 <<< \"open('studio/videos/v/work/state.json','w')\"",
                   "node -e \"require('fs').writeFileSync('studio/videos/v/work/state.json', '')\"",
                   "perl -e 'open(F, \">studio/x\")'", "ruby -e 'File.write(\"studio/x\", \"\")'"]
        stop = ["sh -c 'ls studio'", "bash -c 'cd studio && ls'", "bash <<X\nls studio\nX",
                "python3 -c \"import subprocess; subprocess.run(['s2v', 'tts', 'studio/x'])\"",
                "python3 -c \"import os; os.system('python3 .claude/studio/scripts/state.py next v')\"",
                "python3 -c \"import os; os.environ['S2V_TTS']='x'; open('studio/x')\"",
                "osascript -e 'do shell script \"rm studio/x\"'"]
        for cmd in nonstop:
            d = self.assertDeny(cmd, "G-OPAQUE")
            self.assertTrue(d.message().endswith("\n" + NONSTOP), "%s: %s" % (cmd, d.message()))
        for cmd in stop:
            d = self.assertDeny(cmd)
            self.assertTrue(d.message().endswith("\n" + INV9), "%s: %s" % (cmd, d.message()))

    def test_guard_process_passes_every_deny(self):
        def run(cmd):
            hook = self.hook("Bash", {"command": cmd})
            env = dict(self.env, PYTHONDONTWRITEBYTECODE="1")
            out = subprocess.run([sys.executable, "-B", os.path.join(helpers.SCRIPTS, "guard.py")],
                                 input=json.dumps(hook), capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            return json.loads(out.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertTrue(run("sed x a.txt").endswith("\n" + NONSTOP))
        r = run("sed x a.txt; rm -rf studio/local")
        self.assertIn("(and 1 more)", r)
        self.assertTrue(r.endswith("\n" + INV9))


class EvidenceClasses(unittest.TestCase):
    def test_timing_wording(self):
        e = transcript.NoEvidence("no-question")
        text = approve.evidence_text("state.py approve", "승인 v x", e)
        self.assertIn("run it alone as your next tool call, in the same turn, right after the answer — do not wait "
                      "for the person; never in the same assistant message as the question", text)
        self.assertNotIn("later message", text)

    def raise_sites(self):
        codes = set()
        for name in sorted(os.listdir(GUARD_DIR)):
            if name.endswith(".py"):
                with open(os.path.join(GUARD_DIR, name), encoding="utf-8") as f:
                    codes |= set(re.findall(r'NoEvidence\("([^"]+)"', f.read()))
        return codes

    def test_every_code_in_exactly_one_class(self):
        classes = (approve.REASK_CODES, approve.LABEL_CODES, approve.INV9_CODES)
        for code in transcript.REASONS:
            self.assertEqual(sum(code in c for c in classes), 1, code)
        self.assertEqual(set().union(*classes), set(transcript.REASONS))
        sites = self.raise_sites()
        self.assertIn("summary-not-shown", sites)
        self.assertLessEqual(sites, set(transcript.REASONS))

    def test_suffix_per_class(self):
        for code in approve.REASK_CODES:
            self.assertEqual(approve.evidence_suffix(code), REASK, code)
        self.assertEqual(approve.evidence_suffix("label-not-chosen"), LABEL)
        for code in approve.INV9_CODES:
            self.assertIsNone(approve.evidence_suffix(code), code)
        self.assertIsNone(approve.evidence_suffix(None))
        self.assertIsNone(approve.evidence_suffix("something-new"))
        for code, tail in (("consumed", REASK), ("label-not-chosen", LABEL), ("cancelled", INV9)):
            d = Deny("G-EVIDENCE", "x", suffix=approve.evidence_suffix(code))
            self.assertTrue(d.message().endswith("\n" + tail), code)

    def test_verdicts_carry_the_code(self):
        # every G-EVIDENCE Verdict built from a NoEvidence carries its code; the proxy one without call ids (no
        # NoEvidence) carries none and keeps INV9
        with open(os.path.join(GUARD_DIR, "approve.py"), encoding="utf-8") as f:
            src = f.read()
        calls = re.findall(r'Verdict\("G-EVIDENCE",[^\n]*(?:\n[^\n]*){0,1}', src)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sum("code=e.code" in c for c in calls), 2)
        self.assertTrue(any("gave no session or call id" in c and "code=" not in c for c in calls))

    def test_effect_failure_keeps_inv9(self):
        ctx = judge.Context({"cwd": "/", "tool_name": "Bash"}, {"HOME": "/nonexistent"})

        def fail():
            raise OSError("disk full")
        ctx.effects.append(("G-EVIDENCE", fail))
        judge.finish(ctx)
        self.assertEqual(ctx.denies[0].rule, "G-EVIDENCE")
        self.assertIn("could not record the checked answer", ctx.denies[0].text)
        self.assertTrue(ctx.denies[0].message(ctx.denies).endswith("\n" + INV9))


class CommitEvidenceSuffix(CommitCase):
    # GuardCommit's helpers without its tests (a module-level GuardCommit would run them here too)
    _G = test_guard_commit.GuardCommit
    gate, staged, answer, assertGate = _G.gate, _G.staged, _G.answer, _G.assertGate

    def setUp(self):
        super().setUp()
        self.tpath = TR.transcript_path(self.env, SID)
        self.t = None

    def test_summary_not_shown_and_label(self):
        ok = self.staged()
        self.answer(ok["label"], qtext="이 파일들을 커밋할까요?")  # the summary line was not shown
        d, _ = self.assertGate("git commit -m x", "G-EVIDENCE")
        self.assertIn("summary line", d.message())
        self.assertTrue(d.message().endswith("\n" + REASK), d.message())
        self.answer(ok["label"], chosen="수정해 줘")
        d, _ = self.assertGate("git commit -m x", "G-EVIDENCE")
        self.assertTrue(d.message().endswith("\n" + LABEL), d.message())


class GateEvidenceSuffix(JudgeCase):
    """state.py's gate path: gate-lines-not-shown takes the re-ask suffix through Verdict.code."""

    def test_gate_lines_not_shown(self):
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        tpath = TR.transcript_path(self.env)
        h = "3f2a9c0d1e4b"
        line = '근거: "출국 수속은 2시간 안팎으로 끝납니다." ← "출국 수속은 보통 2시간 안팎이다."'
        st = F.state()
        st["video"] = "v"
        st["langs"]["ko"]["shown"]["2"] = {"-": {"hash": "x", "at": "t", "lines": [line]}}
        with open(os.path.join(self.repo, "studio", "videos", "v", "work", "state.json"), "w") as f:
            json.dump(st, f, ensure_ascii=False)
        label = "승인 v %s" % h
        t = TR.approval_turn(TR.T(), label, qtext="[v] ② 오디션 — hash %s" % h)
        t.write(tpath)
        hook = {"tool_name": "Bash", "cwd": self.repo, "session_id": "sess-1", "transcript_path": tpath,
                "tool_input": {"command": "python3 .claude/studio/scripts/state.py approve v 2 --expect %s" % h},
                "permission_mode": "default", "tool_use_id": "toolu_cmd1", "prompt_id": t.prompt}
        deny, _ = judge.decide(hook, self.env, snapshot_loader=self.loader)
        self.assertEqual(deny and deny.rule, "G-EVIDENCE", deny and deny.message())
        self.assertIn("next tool call, in the same turn", deny.message())
        self.assertTrue(deny.message().endswith("\n" + REASK), deny.message())


if __name__ == "__main__":
    unittest.main()
