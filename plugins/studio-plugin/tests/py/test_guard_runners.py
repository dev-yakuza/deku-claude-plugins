"""G1 runners (guard-runners-plan §1.2, §1.3): the option reader of every runner spec, the outcomes, and a pin that
every runner name has a must-deny and a must-pass case in test_guard_judge."""

import shlex
import unittest

import helpers  # noqa: F401 — sys.path
from stdo.guard import recog, runners
from stdo.guard.model import Word

import test_guard_judge as TJ


def W(text):
    return [Word.lit(x) for x in shlex.split(text)]


def dyn(raw="$X"):
    return Word(raw, None, dynamic=True, dyn=["param:X"], skeleton="\0")


def parse(text, isdir=lambda v: False):
    """`text` starts with the runner name."""
    ws = W(text)
    spec = runners.lookup(recog.key(recog.base(ws[0].value)))
    return runners.parse(spec, ws, 1, isdir=isdir), ws


class Reader(unittest.TestCase):
    def outcome(self, text, **kw):
        return parse(text, **kw)[0].outcome

    def payload(self, text):
        p, ws = parse(text)
        self.assertEqual(p.outcome, "unwrap", "%s: %s" % (text, p.reason))
        return [w.value for w in ws[p.end:]]

    def refused(self, text):
        p, _ws = parse(text)
        self.assertEqual(p.outcome, "refused", text)
        return p.reason

    def test_forms(self):
        # cluster, attached, separate, `=`, `--`
        for t in ("stdbuf -oL rm x", "stdbuf -o L rm x", "stdbuf --output=L rm x", "stdbuf --output L rm x",
                  "stdbuf -i0 -oL -eL rm x", "stdbuf -- rm x", "ionice -c2 -n7 rm x", "ionice -tc2 rm x",
                  "nice -n5 rm x", "nice -5 rm x", "nice --5 rm x", "nice -+5 rm x", "nice --adjustment=5 rm x",
                  "timeout -s KILL 5 rm x", "timeout -sKILL 5 rm x", "timeout --signal=KILL -k 1 5 rm x",
                  "timeout -fpv inf rm x", "timeout -- 5 rm x", "time -p rm x", "time -ao t rm x", "gtime -f %e rm x",
                  "caffeinate -dim -t 5 rm x", "chronic -ev rm x", "unbuffer -p rm x", "setsid -cfw rm x",
                  "flock -sn /tmp/l rm x", "flock -w5 /tmp/l rm x", "flock --timeout=5 /tmp/l rm x",
                  "lockf -kns -t 5 /tmp/l rm x", "xcrun --sdk macosx -v rm x", "sandbox-exec -f p.sb -D a=b rm x",
                  "taskpolicy -b -c utility rm x", "sudo -Eu root -g wheel rm x", "sudo --preserve-env=PATH rm x",
                  "doas -nu root rm x", "watch -n1 -x rm x", "watch --exec -d rm x", "script -aqF log rm x",
                  "env -i -0 -v rm x", "env -C a -u X A=1 rm x", "env -- A=1 rm x", "env - rm x", "nohup -- rm x",
                  "arch -arm64 -e A=1 -d B -c rm x", "arch -arch arm64 -- rm x"):
            self.assertEqual(self.payload(t), ["rm", "x"], t)

    def test_unknown_abbreviation_dynamic(self):
        for t in ("timeout --sig KILL 5 rm x", "stdbuf --out L rm x", "env --argv1 x rm", "env -Z rm",
                  "nohup -x rm", "nice -q rm", "sudo -h x rm", "sudo -R / rm", "sudo --chroot=/ rm", "arch -foo rm",
                  "busybox --install /tmp/b", "busybox -- rm", "time --output-file=x rm", "script -t 0 log rm",
                  "env --ignore-environment=x rm", "flock /tmp/l --verbose rm", "xcrun --help rm"):
            self.assertTrue(self.refused(t), t)
        ws = [Word.lit("stdbuf"), dyn(), Word.lit("rm")]
        self.assertEqual(runners.parse(runners.lookup("stdbuf"), ws, 1).outcome, "refused")
        # a dynamic value of a V option and timeout's DURATION are accepted
        ws = [Word.lit("timeout"), dyn("$T"), Word.lit("rm")]
        p = runners.parse(runners.lookup("timeout"), ws, 1)
        self.assertEqual((p.outcome, p.end), ("unwrap", 2))
        ws = [Word.lit("nice"), Word.lit("-n"), dyn(), Word.lit("rm")]
        self.assertEqual(runners.parse(runners.lookup("nice"), ws, 1).end, 3)
        # a dynamic file is refused
        ws = [Word.lit("time"), Word.lit("-o"), dyn(), Word.lit("ls")]
        self.assertEqual(runners.parse(runners.lookup("time"), ws, 1).outcome, "refused")
        ws = [Word.lit("flock"), dyn(), Word.lit("ls")]
        self.assertEqual(runners.parse(runners.lookup("flock"), ws, 1).outcome, "refused")

    def test_no_command(self):
        for t in ("ionice -p 12", "xcrun --find clang", "xcrun --show-sdk-path", "sudo -l", "sudo -k", "sudo -V",
                  "taskpolicy -p 12", "doas -C /etc/doas.conf", "busybox --list", "arch -h", "env", "env A=1",
                  "nohup", "timeout 5", "flock 3", "lockf 3", "watch", "nice", "script -p log"):
            self.assertEqual(self.outcome(t), "none", t)
        for t in ("ionice -p 12 rm x", "sudo -l rm x", "sudo -v rm x", "xcrun --find clang rm", "busybox --help ls",
                  "arch -h rm"):
            self.assertEqual(self.outcome(t), "refused", t)
        self.assertEqual(self.payload("sudo -k rm x"), ["rm", "x"])  # -k with a command is a flag

    def test_files(self):
        p, ws = parse("time -o out.txt -a ls")
        self.assertEqual([(w.value, op) for w, op in p.files], [("out.txt", "write")])
        p, ws = parse("flock /tmp/l ls")
        self.assertEqual([(w.value, op) for w, op in p.files], [("/tmp/l", "write")])
        p, ws = parse("flock /tmp ls", isdir=lambda v: v == "/tmp")
        self.assertEqual([(w.value, op) for w, op in p.files], [("/tmp", "read")])
        p, ws = parse("flock 3 rm x")
        self.assertEqual(([(w.value, op) for w, op in p.files], p.outcome), ([("3", "write")], "unwrap"))
        p, ws = parse("lockf -t 5 lk make")
        self.assertEqual([(w.value, op) for w, op in p.files], [("lk", "write")])
        p, ws = parse("script -q log ls")
        self.assertEqual([(w.value, op) for w, op in p.files], [("log", "write")])
        p, ws = parse("script -c ls")
        self.assertEqual([(w.value, op) for w, op in p.files], [("typescript", "write")])
        p, ws = parse("script -O o.log -I i.log -T t.log -tx.log -c ls f")
        self.assertEqual(sorted(w.value for w, op in p.files), ["f", "i.log", "o.log", "t.log", "x.log"])
        p, ws = parse("script -p log")
        self.assertEqual([(w.value, op) for w, op in p.files], [("log", "read")])
        p, ws = parse("sudo -e a b")
        self.assertEqual(([(w.value, op) for w, op in p.files], p.outcome), ([("a", "write"), ("b", "write")], "none"))
        p, ws = parse("watch -s shots ls")
        self.assertEqual([(w.value, op) for w, op in p.files], [("shots", "write-dir")])
        p, ws = parse("sandbox-exec -f p.sb ls")
        self.assertEqual([(w.value, op) for w, op in p.files], [("p.sb", "read")])
        p, ws = parse("env --env0-from=e.bin ls")
        self.assertEqual([(w.value, op) for w, op in p.files], [("e.bin", "read")])
        self.assertIn(("unknown",), p.env)

    def test_shell_payloads(self):
        for t, text in (("script -c 'rm x' log", "rm x"), ("script --command='rm x'", "rm x"),
                        ("flock /tmp/l -c 'rm x'", "rm x"), ("flock /tmp/l --command 'rm x'", "rm x"),
                        ("watch 'rm x'", "rm x"), ("watch -n 1 rm x", "rm x")):
            p, ws = parse(t)
            self.assertEqual((p.outcome, " ".join(w.value for w in p.shell)), ("shell", text), t)
        for t in ("flock /tmp/l -c 'rm x' y", "script -c ls log extra", "script", "script -q log",
                  "script -q log -c ls"):
            self.assertEqual(self.outcome(t), "refused", t)
        p, ws = parse("env -iS'rm x' y")
        self.assertEqual((p.outcome, " ".join(w.value for w in p.shell)), ("env-S", "rm x y"))
        self.assertEqual(p.effect, "env-clear")
        p, ws = parse("sudo -s rm x")
        self.assertEqual((p.outcome, [w.value for w in ws[p.end:]]), ("sudo-shell", ["rm", "x"]))
        p, ws = parse("doas -s")
        self.assertEqual(p.outcome, "sudo-shell")

    def test_env_effects(self):
        p, ws = parse("env -i -u A -C d B=1 ls")
        self.assertEqual(p.env[0], ("clear",))
        self.assertIn(("unset", "A"), p.env)
        self.assertEqual([d.value for d in p.chdirs], ["d"])
        self.assertEqual([(e[0], e[1]) for e in p.env if e[0] == "set"], [("set", "B")])
        p, ws = parse("env -P /usr/bin ls")
        self.assertIn("path-modified", p.flags)
        p, ws = parse("xcrun ls")
        self.assertIn("path-modified", p.flags)
        p, ws = parse("sudo A=1 ls")
        self.assertEqual((p.env[0], p.env[1][:2], p.effect), (("clear",), ("set", "A"), "env-clear"))
        p, ws = parse("sudo -E ls")
        self.assertEqual((p.env, p.effect), ([], "user-change"))
        p, ws = parse("sudo -D studio ls")
        self.assertEqual([d.value for d in p.chdirs], ["studio"])
        p, ws = parse("arch -c -e K=V -d D ls")
        self.assertEqual([e[0] for e in p.env], ["clear", "set", "unset"])

    def test_busybox(self):
        for name in ("busybox", "busybox.static", "busybox-x86_64", "toybox", "BUSYBOX"):
            p, ws = parse("%s rm x" % name)
            self.assertEqual((p.outcome, ws[p.end].value), ("next", "rm"), name)
        self.assertEqual(runners.wrapper_name(runners.lookup("toybox"), "toybox"), "toybox")
        self.assertEqual(runners.wrapper_name(runners.lookup("busybox.static"), "busybox.static"), "busybox")
        self.assertEqual(self.outcome("busybox"), "none")

    def test_xargs(self):
        X = runners.XARGS
        for t, end in (("xargs -0 grep x", 2), ("xargs -I{} cat {}", 2), ("xargs -I {} cat {}", 3),
                       ("xargs -P 4 -n1 rm", 4), ("xargs -a f rm", 3), ("xargs --arg-file cat rm", 3),
                       ("xargs --process-slot-var cat rm", 3), ("xargs -i cat {}", 2), ("xargs -i{} cat {}", 2),
                       ("xargs -l2 rm", 2), ("xargs --replace={} rm", 2), ("xargs --max-lines=1 rm", 2),
                       ("xargs -- rm", 2), ("xargs", 1)):
            p = runners.parse(X, W(t), 1)
            self.assertEqual((p.outcome, p.end), ("unwrap", end), t)
        for t in ("xargs --max-lines 1 rm", "xargs --eof x rm", "xargs -Z rm", "xargs --arg rm"):
            self.assertEqual(runners.parse(X, W(t), 1).outcome, "refused", t)

    def test_package_runners(self):
        for t, out in (("npx -y prettier", ("unwrap", "prettier")), ("npx --registry=https://x tsc", ("unwrap", "tsc")),
                       ("npx -p a -p b tsc", ("unwrap", "tsc")), ("npm exec -- tsc", ("unwrap", "tsc")),
                       ("pnpm dlx rimraf x", ("unwrap", "rimraf")), ("bunx --bun x", ("unwrap", "x")),
                       ("yarn dlx -q x", ("unwrap", "x"))):
            ws = W(t)
            p, end = runners.package(recog.key(ws[0].value), ws)
            self.assertEqual((p.outcome, ws[end].value), out, t)
        for t, text in (("npx -c 'rm x'", "rm x"), ("npm exec --call='rm x'", "rm x"), ("npm x -c 'rm x'", "rm x"),
                        ("pnpm exec -c rm x", "rm x"), ("pnpm dlx --shell-mode 'rm x'", "rm x"),
                        ("yarn exec rm x", "rm x")):
            ws = W(t)
            p, _end = runners.package(recog.key(ws[0].value), ws)
            self.assertEqual((p.outcome, " ".join(w.value for w in p.shell)), ("shell", text), t)
        for t in ("npx --weird x", "npx -c 'rm x' y", "pnpm exec --nope x", "npx --reg x"):
            ws = W(t)
            p, _end = runners.package(recog.key(ws[0].value), ws)
            self.assertEqual(p.outcome, "refused", t)
        self.assertEqual(runners.package("npm", W("npm test")), (None, None))

    def test_refused_list(self):
        for t in ("su -c x", "chroot / ls", "unshare -r ls", "expect -c x", "tmux new -d", "uv run x", "bundle exec x",
                  "mise x -- ls", "leaks --atExit -- ls", "dtrace -qc ls", "launchctl submit -l x -- ls", "zargs -- a",
                  "at now"):
            ws = W(t)
            self.assertTrue(runners.refused_reason(recog.key(ws[0].value), ws[1:]), t)
        for t in ("uv pip install x", "bundle install", "mise ls", "leaks 12", "dtrace -n BEGIN",
                  "launchctl list", "direnv allow"):
            ws = W(t)
            self.assertIsNone(runners.refused_reason(recog.key(ws[0].value), ws[1:]), t)
        self.assertTrue(runners.refused_reason("uv", [dyn()]))


class Review1(unittest.TestCase):
    """G1 implementation review 1: xcrun's one-dash long options (m6), --help/--version (C-m1), npm options before
    the subcommand and npm_config_call (M5), the dropped-value rule (M4)."""

    def test_xcrun(self):
        for t in ("xcrun -sdk macosx --show-sdk-path", "xcrun -find clang", "xcrun -f clang", "xcrun --find clang",
                  "xcrun -show-sdk-path", "xcrun -sdk macosx -show-sdk-version"):
            self.assertEqual(parse(t)[0].outcome, "none", t)
        for t in ("xcrun -sdk macosx rm x", "xcrun -toolchain x -v rm x"):
            p, ws = parse(t)
            self.assertEqual((p.outcome, ws[p.end].value), ("unwrap", "rm"), t)
        for t in ("xcrun -f rm -rf x", "xcrun -bogus rm"):
            self.assertEqual(parse(t)[0].outcome, "refused", t)

    def test_help_and_version(self):
        for t in ("env --help", "nohup --help", "nohup --version", "timeout --help", "nice --version",
                  "stdbuf --help", "time --version", "flock -h", "setsid -V", "ionice --help", "script -V",
                  "watch -v"):
            self.assertEqual(parse(t)[0].outcome, "none", t)
        for t in ("env --help rm x", "timeout --help 5 rm x", "nohup --help rm x"):
            self.assertEqual(parse(t)[0].outcome, "refused", t)
        self.assertEqual(runners.parse(runners.XARGS, W("xargs --version"), 1).outcome, "none")
        for t in ("npx --version", "npx -v", "npx --help", "npm exec --help"):
            ws = W(t)
            p, _end = runners.package(recog.key(ws[0].value), ws)
            self.assertEqual(p.outcome, "none", t)

    def test_options_before_the_subcommand(self):
        for t, text in (("npm --call='rm x' exec", "rm x"), ("npm -c 'rm x' exec", "rm x"),
                        ("npm --loglevel=silent exec -c 'rm x'", "rm x"), ("pnpm --silent exec -c 'rm x'", "rm x"),
                        ("pnpm --shell-mode exec 'rm x'", "rm x")):
            ws = W(t)
            p, _end = runners.package(recog.key(ws[0].value), ws)
            self.assertEqual((p.outcome, " ".join(w.value for w in p.shell)), ("shell", text), t)
        for t, prog in (("npm --yes exec rimraf x", "rimraf"), ("npm --prefix . exec -- tsc", "tsc"),
                        ("pnpm -r exec rm x", "rm"), ("bun x tsc", "tsc")):
            ws = W(t)
            p, end = runners.package(recog.key(ws[0].value), ws)
            self.assertEqual((p.outcome, ws[end].value), ("unwrap", prog), t)
        for t in ("npm --silent run build", "bun -e 'x'", "npm test"):
            ws = W(t)
            self.assertEqual(runners.package(recog.key(ws[0].value), ws), (None, None), t)

    def test_npm_config_call(self):
        env = {"npm_config_call": Word.lit("rm x")}
        for t in ("npm exec", "npx"):
            ws = W(t)
            p, _end = runners.package(recog.key(ws[0].value), ws, env)
            self.assertEqual((p.outcome, [w.value for w in p.shell]), ("shell", ["rm x"]), t)
        ws = W("npm exec rimraf x")
        p, _end = runners.package("npm", ws, {"NPM_CONFIG_CALL": Word.lit("rm x")})
        self.assertEqual(p.outcome, "refused")

    def test_number_refused(self):
        nice, timeout = runners.lookup("nice"), runners.lookup("timeout")
        self.assertTrue(runners.number_refused(nice, "-n", Word.lit("rm")))
        self.assertFalse(runners.number_refused(nice, "-n", Word.lit("5")))
        self.assertFalse(runners.number_refused(timeout, "-s", Word.lit("rm")))  # a signal name: not a number
        self.assertFalse(runners.number_refused(timeout, "-k", Word.lit("1.5s")))


class CmdOpts(unittest.TestCase):
    """cmdopts readers changed in G1 implementation review 1 (M7, M8, M9/C-M2, M10, M12, M13, C-m2)."""

    def test_long_option_prefixes(self):
        from stdo.guard.cmdopts import long_option as L
        self.assertTrue(L("--exe", ("--exec",)))
        self.assertTrue(L("--upload-p=x", ("--upload-pack",)))
        self.assertTrue(L("--use-comp=x", ("--use-compress-program",)))
        self.assertFalse(L("--to", ("--to-cmd",), exact=("--to",)))
        self.assertFalse(L("--tool=vimdiff", ("--tool-cmd",), exact=("--tool",)))
        self.assertFalse(L("--", ("--exec",)))
        self.assertFalse(L("-x", ("--exec",)))
        self.assertFalse(L("--execute", ("--exec",)))

    def test_git_options(self):
        from stdo.guard.cmdopts import git_option_problem as G
        for sub, args in (("rebase", ["--exe", "x"]), ("ls-remote", ["--upload-p=x", "."]),
                          ("push", ["--receive-p=x"]), ("grep", ["--open-files=x"]), ("difftool", ["--extc=x"]),
                          ("clone", ["--templ=/t", "r"]), ("archive", ["--exe=x"]), ("send-email", ["--sendmail-c=x"]),
                          ("ls-remote", ["ext::sh -c x"]), ("remote", ["add", "x", "ext::sh"]),
                          ("archive", ["--remote=ext::sh"])):
            self.assertTrue(G(sub, args), (sub, args))
        for sub, args in (("commit", ["-m", "docs: ext:: urls"]), ("send-email", ["--to", "a@b"]),
                          ("mergetool", ["--tool=vimdiff"]), ("commit", ["-m", "ext::x"])):
            self.assertIsNone(G(sub, args), (sub, args))

    def test_config_routes(self):
        from stdo.guard import cmdopts as C
        self.assertEqual(C.config_renames(["--rename-section", "x", "core"]), ["core"])
        self.assertEqual(C.config_renames(["rename-section", "x", "alias"]), ["alias"])
        self.assertEqual(C.config_renames(["--global", "--rename-section", "x", None]), [None])
        self.assertEqual(C.config_renames(["x.y", "z"]), [])
        for sec in ("core", "alias", "diff.x", "difftool.x", None):
            self.assertTrue(C.command_section(sec), sec)
        for sec in ("x", "user", "color"):
            self.assertIsNone(C.command_section(sec), sec)
        self.assertEqual(C.command_key(None), "a -c the guard cannot read")
        self.assertTrue(C.command_key("remote.x.url", "ext::sh -c x"))
        self.assertTrue(C.command_key("url.ext::sh -c x.insteadOf", "https://"))
        self.assertIsNone(C.command_key("remote.x.url", "https://example.invalid/r.git"))

    def test_config_pairs(self):
        from stdo.guard import cmdopts as C
        d = Word("$A", None, dynamic=True, dyn=["param:A"], skeleton="\0")
        k = Word("core.editor=$A", None, dynamic=True, dyn=["param:A"], skeleton="core.editor=\0")
        self.assertEqual(C.config_pair(d), (None, None))
        self.assertEqual(C.config_pair(k), ("core.editor", None))
        self.assertEqual(C.config_pair(Word.lit("a.b=c")), ("a.b", "c"))
        for ws, want in (([Word.lit("-c"), d, Word.lit("r")], [(None, None)]),
                         ([Word.lit("--config"), k], [("core.editor", None)]),
                         ([Word("--config=$A", None, dynamic=True, skeleton="--config=\0")], [(None, None)]),
                         ([Word.lit("--conf=core.hooksPath=/h")], [("core.hooksPath", "/h")]),
                         ([Word.lit("-ccore.x=y")], [("core.x", "y")]), ([d, Word.lit("r")], [])):
            self.assertEqual(C.clone_configs(ws), want, [w.raw for w in ws])

    def test_paramx_and_zstyle(self):
        from stdo.guard import cmdopts as C
        for raw in ("${${(e)X}}", "${Y:-${(e)X}}", "${X/(#m)*/${(e)MATCH}}"):
            self.assertEqual(C.paramx_problem(raw), "eval", raw)
        self.assertIsNone(C.paramx_problem("${(s:e:)X}"))
        self.assertEqual(C.paramx_problem("${X:-${commands[ls]::=x}}"), "table")
        self.assertEqual(C.paramx_assigned("${X:-${GIT_EDITOR:=x}}"), ["GIT_EDITOR"])
        for vals in ([":vcs_info:*", "command", "x"], ["*", "command", "x"], [None, "k", "v"]):
            self.assertTrue(C.zstyle_problem(vals), vals)
        for vals in ([":completion:*", "menu", "select"], ["-L"], ["-s", ":x", "k", "out"]):
            self.assertIsNone(C.zstyle_problem(vals), vals)
        self.assertEqual(C.written_names("read", ["-r", "line"]), ["line"])
        self.assertEqual(C.written_names("set", ["-A", "GIT_EDITOR", "rm"]), ["GIT_EDITOR"])
        self.assertEqual(C.written_names("zparseopts", ["e:=GIT_EDITOR"]), ["GIT_EDITOR"])


class UnknownFolder(unittest.TestCase):
    """§1.7a: `**/<rel>` under a folder the guard cannot tell, and the two-pattern matcher it uses."""

    def test_matcher(self):
        from stdo.guard import protect
        from stdo.guard.protect import glob_may_match as M
        self.assertTrue(M(["**", "state.json"], ["studio", "**", "videos", "*", "work", "state.json"], False))
        self.assertTrue(M(["studio", "**"], ["studio", "local", "**"], False))
        self.assertTrue(M(["studio", "l*"], ["studio", "local", "**"], False, prefix=True))
        self.assertFalse(M(["src", "*.ts"], ["studio", "local", "**"], False, prefix=True))
        self.assertTrue(M(["STUDIO", "local"], ["studio", "local", "**"], True))
        self.assertFalse(M(["STUDIO", "local"], ["studio", "local", "**"], False))
        self.assertTrue(M(["s[^x]udio", "local"], ["studio", "local", "**"], False))  # `[` matches every name
        self.assertTrue(M(["stu(d)io"], ["studio"], False))
        self.assertFalse(M(["^x"], ["studio"], False))
        self.assertTrue(M(["^x"], ["studio"], False, extglob=True))
        # G1 §2 (part B): `|`, `<1-3>`, and `~ #` only under extendedglob; `?`; a wildcard against a table wildcard
        self.assertTrue(M(["a|b"], ["studio"], False))
        self.assertFalse(M(["v<1-3>"], ["studio"], False))  # review 9 conf m-1: one or more digits in the range
        self.assertTrue(M(["v<1-3>"], ["v2"], False))
        self.assertFalse(M(["v<1-3>"], ["v4"], False))
        self.assertTrue(M(["v<->"], ["v*"], False))
        self.assertTrue(M(["<->x"], ["007x"], False))
        self.assertFalse(M(["s<->tudio"], ["studio"], False))
        for g in ("studio~y", "studi#o", "stu#dio", "studi##o", "s[t]udio"):
            self.assertFalse(M([g], ["studio"], False), g) if "[" not in g else None
            self.assertTrue(M([g], ["studio"], False, extglob=True), g)
        # review 6 conf m-1: extended globs are matched as zsh reads them (a trailing `~` is a letter)
        for g in ("x~y", "x#", "notes#1", "a.txt~", "*~", "^studio", "stud~io", "s[!t]udio"):
            self.assertFalse(M([g], ["studio"], False, extglob=True), g)
        # review 7 B1, M2: in a bracket expression `~ ^ #` are members, `]` first is a member, `]-^` is no range, a
        # `[:class:]` is a class (an unknown name adds nothing); the word is not split at a `/` inside brackets
        for g in ("[s~]tudio", "[~s]tudio", "stu[d~]io", "studi[o~]", "[s#]tudio", "[s^]tudio", "[]s]tudio", "[!]tudio",
                  "[[:lower:]]tudio", "[![:foo:]]tudio", "[r-t]tudio", "[^x]tudio"):
            self.assertTrue(M([g], ["studio"], False, extglob=True), g)
            self.assertTrue(M([g], ["studio"], False), g)
        for g in ("[]tudio", "[[:foo:]]tudio", "*[~]", "x[~]y", protect.Seg("[r-t]tudio", set(range(10)) - {2})):
            self.assertFalse(M([g], ["studio"], False, extglob=True), g)  # `[r\-t]`: a quoted `-` is a letter
        self.assertTrue(M(["pre[]-^]commit"], ["pre-commit"], False))
        self.assertTrue(M(["^stu[d]io~~x"], ["studio"], False, extglob=True))  # `~~`: unsure, every name
        self.assertEqual(protect.pattern_segments("[s/]tudio/local"), ["[s/]tudio", "local"])
        self.assertEqual(protect.ext_cut(protect.pattern_segments("[s~]tudio~x/y"), True), ["[s~]tudio"])
        self.assertTrue(M(["studio", "videos", "?", "work", "state.json"],
                          ["studio", "**", "videos", "*", "work", "state.json"], False))
        self.assertTrue(M(["studio", "videos", "v", "work", "x*"],
                          ["studio", "**", "videos", "*", "work", "gate4b-lines.*.txt"], False))
        self.assertFalse(M(["src", "*.ts"], ["studio", "**", "voices", "**"], False))
        self.assertTrue(M(["**", "*.pyc"], [".claude", "studio", "scripts", "**"], False))  # `**` on both sides
        # anchors: a table `**` may not stand for every anchored segment
        self.assertFalse(M(["**", "local", "a.txt"], ["studio", "**", "voices", "**"], False, anchors={1}))
        self.assertTrue(M(["**", "voices", "a.txt"], ["studio", "**", "voices", "**"], False, anchors={1}))

    def test_hits(self):
        from stdo.guard.protect import unknown_folder_hit as H
        for rel, op in ((["local"], "delete"), (["work"], "delete"), (["state.json"], "write"),
                        (["studio"], "delete"), ([".claude"], "delete"), (["voices"], "write"),
                        (["studio", "config.json"], "write"), (["cast", "a", "status.json"], "write"),
                        (["work", "source"], "delete"), (["studio", "videos", "v", "work", "state.json"], "write")):
            self.assertIsNotNone(H(rel, "studio", False, op), rel)
        for rel, op in ((["a.txt"], "write"), (["node_modules"], "delete"), (["notes.md"], "write"),
                        (["config.json"], "write"), (["source"], "delete"), (["status.json"], "write"),
                        (["local", "a.txt"], "write"), (["out.log"], "write"), ([".cache"], "delete")):
            self.assertIsNone(H(rel, "studio", False, op), rel)
        self.assertEqual(H(["studio"], "studio", False, "delete"), "P-ANC")
        self.assertIsNone(H(["voices"], "studio", False, "write", skip={"P-VOICE"}))


class Review2(unittest.TestCase):
    """G1 implementation review 2: the dropped-value rule only when the runner certainly rejects the word (M2), option
    values that keep a wildcard (M12), the readers of attached names (M3), flag groups (M8), zstyle patterns (M9),
    clone clusters (M5), renamed sections (M6), send-email (M7), make (M15) and tar (M16)."""

    def test_number_refused_certain_only(self):
        timeout, nice = runners.lookup("timeout"), runners.lookup("nice")
        for v in (" 5", "0x1p1", "1e1", "inf", "-inf", "nan", "infs", "5x", "+.5"):
            self.assertFalse(runners.number_refused(timeout, "-k", Word.lit(v)), v)
        for v in ("KILL", "-Z", "--sig=KILL", "rm", "x"):
            self.assertTrue(runners.number_refused(timeout, "-k", Word.lit(v)), v)
        self.assertTrue(runners.number_refused(nice, "-n", Word.lit("rm")))
        self.assertFalse(runners.number_refused(nice, "-n", dyn()))

    def test_attached_values_keep_wildcards(self):
        for t in ("env --chdir=stu?io ls", "env -Cs*/videos ls"):
            ws = W(t)
            ws[1].glob = True
            p = runners.parse(runners.lookup("env"), ws, 1)
            self.assertTrue(p.chdirs[-1].glob, t)
        p = runners.parse(runners.lookup("env"), W("env --chdir=studio ls"), 1)
        self.assertFalse(p.chdirs[-1].glob)

    def test_attached_names(self):
        from stdo.guard import cmdopts as C
        for prog, vals, names in (("print", ["-vcommands[ls]", "x"], ["commands[ls]"]),
                                  ("print", ["-rvfunctions[ls]", "x"], ["functions[ls]"]),
                                  ("print", ["-nvGIT_EDITOR", "x"], ["GIT_EDITOR"]),
                                  ("set", ["-Acommands", "ls"], ["commands"]), ("set", ["+Acommands"], ["commands"]),
                                  ("strftime", ["-sGIT_EDITOR", "x", "0"], ["GIT_EDITOR"]),
                                  ("zparseopts", ["-AGIT_EDITOR", "a"], ["GIT_EDITOR"]), ("print", ["-u2", "x"], [])):
            self.assertEqual(C.attached_names(prog, vals), names, (prog, vals))
        self.assertTrue(C.name_writer("set", ["-Acommands", "ls"]))
        self.assertIn("GIT_EDITOR", C.written_names("print", ["-vGIT_EDITOR", "x"]))
        self.assertIn("commands", C.written_names("set", ["-Acommands", "ls"]))

    def test_flag_groups(self):
        from stdo.guard import cmdopts as C
        for raw in ("${(s(x)e)X}", "${(s{)}e)X}", "${(s[x]e)X}", "${(s<x>e)X}", "${(s.x.e)X}", "${(r:2::x:e)X}",
                    "${(ee)X}", "${(%e)X}", "${(e"):
            self.assertEqual(C.paramx_problem(raw), "eval", raw)
        for raw in ("${(j:e:)X}", "${(l:3::e:)X}", "${(s:e:)X}", "${(%)X}"):
            self.assertNotEqual(C.paramx_problem(raw), "eval", raw)
        self.assertEqual(C.paramx_problem("${(s(x))commands::=x}"), "table")
        self.assertEqual(C.paramx_assigned("${(s(x))GIT_EDITOR::=x}"), ["GIT_EDITOR"])

    def test_zstyle_patterns(self):
        from stdo.guard import cmdopts as C
        for vals in (["--", ":vcs_info:*", "command", "x"], [":v(c)s_info:*", "command", "x"],
                     [":vcs_(info|x):*", "command", "x"], [":vcs\\_info:*", "command", "x"], [":vcs*", "command", "x"],
                     [":vcs_inf?:*", "command", "x"], [":v[c]s_info:*", "command", "x"]):
            self.assertTrue(C.zstyle_problem(vals), vals)
        for vals in ([":completion:*", "menu", "select"], ["--", ":completion:*", "menu", "select"],
                     [":prompt:*", "x", "y"], ["-s", ":vcs_info:*", "command", "x"]):
            self.assertIsNone(C.zstyle_problem(vals), vals)

    def test_clone_clusters(self):
        from stdo.guard import cmdopts as C
        for t, want in (("-qc core.hooksPath=/h /r sub", [("core.hooksPath", "/h")]),
                        ("-qccore.hooksPath=/h /r", [("core.hooksPath", "/h")]),
                        ("-nc core.hooksPath=/h /r", [("core.hooksPath", "/h")]),
                        ("-o origin -c a.b=c /r", [("a.b", "c")]), ("-q /r sub", [])):
            self.assertEqual(C.clone_configs(W("x " + t)[1:]), want, t)

    def test_renamed_sections(self):
        from stdo.guard import cmdopts as C
        for sec in ("includeIf.onbranch:main", "includeif.gitdir:/x", "hook.pre", "url.ext::sh", "sendemail",
                    "difftool.x", "pager"):
            self.assertTrue(C.command_section(sec), sec)
        for sec in ("x", "y", "user", "submodule.s"):
            self.assertIsNone(C.command_section(sec), sec)

    def test_send_email_one_dash(self):
        from stdo.guard.cmdopts import git_option_problem as G
        for args in (["-sendmail-cmd=x"], ["-sendm=x"], ["-to-cmd=x"], ["-cc-cmd", "x"], ["-header-cmd=x"],
                     ["-smtp-server=/tmp/evil"], ["-smtp-s", "/tmp/evil"]):
            self.assertTrue(G("send-email", args), args)
        for args in (["-to", "a@example.invalid"], ["--cc", "a@example.invalid"],
                     ["-smtp-server=smtp.example.invalid"]):
            self.assertIsNone(G("send-email", args), args)

    def test_make_and_tar(self):
        from stdo.guard.cmdopts import program_option_problem as P
        for vals in (["-sf", "-", "x"], ["-kf", "/dev/stdin", "x"], ["-if-", "x"], ["-C", "src", "-sf", "-", "x"]):
            self.assertTrue(P("make", vals), vals)
        for vals in (["-j4", "-f", "Makefile"], ["-sC", "src"], ["-k", "test"]):
            self.assertIsNone(P("make", vals), vals)
        self.assertTrue(P("tar", ["-cf", "x.tar", "--checkpoint-action", "exec=rm -rf x", "a"]))
        self.assertTrue(P("tar", ["-cf", "x.tar", "--checkpoint-action", None, "a"]))
        self.assertIsNone(P("tar", ["-cf", "x.tar", "--checkpoint=1", "--checkpoint-action", "dot", "a"]))

    def test_unknown_folder_dots_and_wildcards(self):
        from stdo.guard.protect import unknown_folder_hit as H
        for rel, op in ((["*"], "delete"), (["s*"], "delete"), (["*"], "write-dir"), (["*"], "write"),
                        (["*.json"], "write")):
            self.assertIsNotNone(H(rel, "studio", False, op), rel)
        self.assertEqual(H(["*"], "studio", False, "delete"), "P-ANC")
        for rel, op in ((["*.log"], "delete"), (["*.ts"], "write"), (["*.bak"], "delete")):
            self.assertIsNone(H(rel, "studio", False, op), rel)


class Review3(unittest.TestCase):
    """G1 implementation review 3: npm's abbreviated --call (bypass M1), leaks' one-dash -atExit (M2)."""

    def test_npm_call_prefixes(self):
        for t in ("npm exec --c='rm x'", "npx --c='rm x'", "npm --c='rm x' exec", "npm x --c='rm x'", "npx --c 'rm x'",
                  "npm --c 'rm x' exec", "npx ---c='rm x'", "npm exec --cal='rm x'", "npx --CALL='rm x'"):
            ws = W(t)
            p, _end = runners.package(recog.key(ws[0].value), ws)
            self.assertEqual((p.outcome, " ".join(w.value for w in p.shell)), ("shell", "rm x"), t)
        for t, out in (("npx --cache=/tmp/c tsc", ("unwrap", "tsc")), ("npm --prefix . exec -- tsc", ("unwrap", "tsc"))):
            ws = W(t)
            p, end = runners.package(recog.key(ws[0].value), ws)
            self.assertEqual((p.outcome, ws[end].value), out, t)

    def test_leaks_at_exit(self):
        for t in ("leaks -atExit -- ls", "leaks -atexit -- ls", "leaks --atExit -- ls", "leaks -atExit ls",
                  "leaks -at -- ls"):
            ws = W(t)
            self.assertTrue(runners.refused_reason("leaks", ws[1:]), t)
        for t in ("leaks 12", "leaks -list 12"):
            ws = W(t)
            self.assertIsNone(runners.refused_reason("leaks", ws[1:]), t)


class Pins(unittest.TestCase):
    def names(self, cmd):
        try:
            ws = shlex.split(cmd)
        except ValueError:
            ws = cmd.split()
        return {recog.key(recog.base(w)) for w in ws}

    def test_every_runner_has_cases(self):
        deny = [c for c, _r in TJ.MUST_DENY]
        for name in sorted(set(runners.SPECS)):
            self.assertTrue(any(name in self.names(c) for c in deny), "no MUST_DENY case for %s" % name)
            self.assertTrue(any(name in self.names(c) for c in TJ.MUST_PASS), "no MUST_PASS case for %s" % name)


if __name__ == "__main__":
    unittest.main()
