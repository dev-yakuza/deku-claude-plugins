"""M0d-1a: the scanner against real shells (m0d1a-plan §10.13, hermetic).

Each case runs under `env -i HOME=<tmp home> PATH=<recorder dir> REC_LOG=<log> zsh -f -c <cmd>` (and
`bash --norc --noprofile -c` for reference) in a temporary folder. The recorder dir holds only
recorders (they write their argv and cwd and do nothing). Every path a case touches is checked to
be under the temporary folder before it runs. Aliases, functions and snapshot options are covered
by the fake-snapshot tests (test_guard_snapshot), not here.
"""

import json
import os
import shutil
import subprocess
import sys
import unittest

import helpers
from guard_base import GuardCase

ZSH = shutil.which("zsh") or ("/bin/zsh" if os.path.exists("/bin/zsh") else None)
BASH = "/bin/bash" if os.path.exists("/bin/bash") else shutil.which("bash")
RECORDED = ("rm", "cp", "mv", "touch", "s2v", "git", "rec", "mkdir", "yarn", "tee")

CASES = [
    "rec 'a;b && c | d $(x) `y` # z'",
    'rec "a\\"b \\$x \\` \\\\ \\a"',
    'rec "ab\\\ncd"',
    "rec $'a\\tb\\x41\\101\\'q'",
    "rec a'b'\"c\"$'d' '' \"\"",
    "rec a \\\n b",
    "re\\\nc x",
    "rec 'a\\\nb'",
    "rec a # c\nrm b",
    "rec a#b",
    "rec a # don't\nrm studio-x",
    "rec a&&rm b",
    "rec a|rec b;rec c",
    'rec "a && b" a\\;b \'x;y\'',
    "rec 스튜디오/파일 🎬 a\u00a0b",
    "rec a\\",
    "cd x && touch y",
    "cd nope; touch y",
    "cd x; touch y",
    "cd nope || true; touch y",
    "( cd x; rm y ); rm z",
    "{ cd x; rm y; }; rm z",
    "{ rm x }; rm y",
    "( ( cd a; ( cd b; rm c ) ); rm d )",
    "rec $(cd x && rec in) ; rm y",
    "cd x; cd -; touch y",
    "cd ..; touch y",
    "cd link/..; touch y",
    "setopt autopushd; cd a; cd b; popd; touch c",
    "pushd a; pushd b; popd; touch c",
    "true | cd x; touch y",
    "cd x | true; touch y",
    "if test -d x; then cd x; fi; rm y",
    "for d in a b; do rm $d; done; rm g",
    "X=studio; rm -rf $X/local",
    "X=a rm $X",
    "rec {a,b}.json {1..3} {a,{b,c}} '{a,b}'",
    "rec ~ ~/x",
    "rec --out=~/x",
    "export X=a:~/b; rec $X",
    "Y=~/q; rec $Y",
    "rec \"$(rec inner)\"/local",
    "yarn --cwd sub x",
    "git -C a status",
    "\\rm x",
    "r\\m x",
    "'r'm x",
    "$'\\x72m' x",
    "cat <<EOF > out.txt\nhi $(rec hd)\nEOF\nrm z",
    "rec <<'EOF'\n$(rm nope)\nEOF\n",
    "rec 'it''s'",
    "case b in (a|b) rm one;; c) rm two;; esac",
    # implementation review round 1 repros
    "X=a/b.c; rec $X:h $X:t $X:s/a/z/ \"$X:h\" ${X}:h $X:/q",
    "X=a; rec $=X $+X $^X $~X",
    "rec ~+ ~+/q",
    "cd x; rec ~-",
    "cd ~+/x; touch y",
    "eval 'cd x'; touch y",
    "emulate sh -c 'rm a'; touch y",
    "CDPATH=a cd b; touch y",
    "cd -P link/..; touch y",
    "setopt chaselinks; cd link/..; touch y",
    "cd link/..; touch y",
    "setopt shwordsplit; X='a b'; rm $X",
    "set -o globsubst; X='*'; rm $X",
    "setopt ignorebraces; rec {a,b}",
    "emulate sh; X='a b'; rm $X",
    "disable cd; cd x; touch y",
    "rec $'\\c@x|\\q'",
    # implementation review round 2 repros
    "pushd x; pushd b; popd; touch c",
    "setopt autopushd; cd nope; cd a; popd; touch c",
    "f() { setopt shwordsplit }; f; X='a b'; rec $X",
    "f() { emulate -L zsh; setopt shwordsplit }; f; X='a b'; rec $X",
]
UNSUPPORTED = ["function { rm a }", "() { rm a }", "function () { rm a; }"]


def recorder(path, log):
    with open(path, "w") as f:
        f.write("#!%s -I\nimport json, os, sys\n"
                "with open(os.environ['REC_LOG'], 'a') as f:\n"
                "    f.write(json.dumps({'argv': [os.path.basename(sys.argv[0])] + sys.argv[1:], 'cwd': os.getcwd()})"
                " + '\\n')\n" % sys.executable)
    os.chmod(path, 0o755)


@unittest.skipUnless(ZSH, "zsh is not installed")
class RealShell(GuardCase):
    def setUp(self):
        super().setUp()
        self.rec = os.path.join(self.tmp, "rec-bin")
        os.makedirs(self.rec)
        self.log = os.path.join(self.tmp, "rec.log")
        for n in RECORDED:
            recorder(os.path.join(self.rec, n), self.log)
        self.home = os.path.join(self.tmp, "rhome")
        os.makedirs(self.home)
        self.env["HOME"] = self.home
        self.env["PATH"] = self.rec + ":/usr/bin:/bin"
        self.env.pop("OLDPWD", None)

    def fresh_dir(self):
        d = os.path.join(self.tmp, "case")
        if os.path.exists(d):
            shutil.rmtree(d)
        os.makedirs(d)
        for sub in ("x", "a/b", "b", "sub", "t/inner"):
            os.makedirs(os.path.join(d, sub), exist_ok=True)
        os.symlink(os.path.join(d, "t", "inner"), os.path.join(d, "link"))
        return os.path.realpath(d)

    def run_shell(self, argv, cmd, cwd):
        if os.path.exists(self.log):
            os.remove(self.log)
        env = ["env", "-i", "HOME=%s" % self.home, "PATH=%s" % self.rec, "REC_LOG=%s" % self.log]
        subprocess.run(env + argv + [cmd], cwd=cwd, capture_output=True, timeout=20)
        calls = []
        if os.path.exists(self.log):
            with open(self.log) as f:
                calls = [json.loads(line) for line in f if line.strip()]
        return calls

    def check_paths(self, scan, root):
        for c in scan.commands:
            for d in c.cwds:
                self.assertTrue(d.startswith(self.tmp), (scan.raw, d))
            for w in c.words[1:] + [r.target for r in c.redirs if r.target is not None]:
                v = w.value
                if v and "/" in v and not v.startswith("-") and not v.startswith(("a/", "studio")):
                    p = v if os.path.isabs(v) else os.path.join(c.cwds[0] if c.cwds else root, v)
                    self.assertTrue(os.path.normpath(p).startswith(self.tmp), (scan.raw, v))

    def test_cases_match_zsh(self):
        mismatches = []
        for cmd in CASES:
            root = self.fresh_dir()
            r = self.scan(cmd, cwd=root)
            self.assertEqual(r.status, "ok", (cmd, r.reason))
            self.check_paths(r, root)
            calls = self.run_shell([ZSH, "-f", "-c"], cmd, root)
            scanned = [c for c in r.commands if c.prog in RECORDED]
            # every real call is covered: exactly (literal argv) or by a scanned command with dynamic words
            for call in calls:
                exact = [c for c in scanned if all(a is not None for a in c.argv) and [c.prog] + c.argv[1:] == call["argv"]]
                wild = [c for c in scanned if c.prog == call["argv"][0] and any(a is None for a in c.argv)]
                inside = [o for o in r.opaque if o.payload is None or " ".join(call["argv"]) in o.payload]
                if not exact and not wild and not inside:
                    mismatches.append((cmd, "not scanned", call["argv"]))
                    continue
                if not exact and not wild:
                    continue  # it ran inside an opaque part (eval, emulate -c …): covered by that part
                real = os.path.realpath(call["cwd"])
                if not any(not c.cwds or real in [os.path.realpath(x) for x in c.cwds] for c in exact + wild):
                    mismatches.append((cmd, "cwd", call, [c.cwds for c in exact + wild]))
            # every literal scanned command ran, unless it sits in a branch that may not run
            ran = [c["argv"] for c in calls]
            for c in scanned:
                if all(a is not None for a in c.argv) and [c.prog] + c.argv[1:] not in ran \
                        and not set(c.ctx) & {"cond", "loop"}:
                    mismatches.append((cmd, "did not run", c.argv))
        self.assertEqual(mismatches, [])

    def test_unsupported_forms_are_real_zsh(self):
        for cmd in UNSUPPORTED:
            root = self.fresh_dir()
            r = self.scan(cmd, cwd=root)
            self.assertEqual(r.status, "unparsable", cmd)
            calls = self.run_shell([ZSH, "-f", "-c"], cmd, root)
            self.assertEqual([c["argv"] for c in calls], [["rm", "a"]], cmd)  # zsh runs it: not a scanner gap

    @unittest.skipUnless(BASH, "bash is not installed")
    def test_bash_reference_alt(self):
        root = self.fresh_dir()
        r = self.scan("rec --out=~/x", cwd=root)
        w = r.commands[0].words[1]
        calls = self.run_shell([BASH, "--norc", "--noprofile", "-c"], "rec --out=~/x", root)
        # bash may or may not expand here (version dependent); the scanner keeps both readings
        self.assertIn(calls[0]["argv"][1], (w.value, w.alt))

    def test_zsh_parse_errors_run_nothing(self):
        root = self.fresh_dir()
        self.assertEqual(self.run_shell([ZSH, "-f", "-c"], "rec a }", root), [])
        r = self.scan("rec a }", cwd=root)  # the scanner keeps `}` as an argument: it judges more, not less
        self.assertEqual(r.status, "ok")

    def test_helpers_isolated(self):
        self.assertNotEqual(self.home, os.environ.get("STUDIO_TEST_REAL_HOME"))
        self.assertTrue(helpers.full_mode() in (True, False))
