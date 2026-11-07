"""Programs that run another program (G1 plan §1.2, §1.3): data (`SPECS`, one per runner) and one reader,
`parse(spec, words, i, isdir)` -> Parsed. walk.process calls it for every name in SPECS; judge reads the result from
`cmd.wrappers` (their `files` and `cwd`), `cmd.files` and the opaques walk emits.

One getopt-like reading for every runner: options only before the first operand (no permutation), `--` ends them,
a short cluster is read letter by letter (a value letter takes the rest of the cluster or the next word), long
options by exact name only (`--name=value`; `--name value` only for value options). An unknown option, an
abbreviation, a dynamic word where an option, an operand or a file is expected: refused — the guard cannot tell
what runs. Outcomes: unwrap (the payload is the next program), none (the runner runs nothing; it is the program),
shell (the payload is a shell string), refused."""

import re

from .model import Word

# option kinds
F, V, W, R, D, C = "F", "V", "W", "R", "D", "C"  # flag, value (ignored), file written, file read, folder written,
U, N, NV, S = "U", "N", "NV", "S"  # run folder; env unset; no command (flag / with a value); shell payload
CLEAR, KEEP, PATHDIR, ENVFILE, SPLIT = "CLEAR", "KEEP", "PATHDIR", "ENVFILE", "SPLIT"
FIND = "FIND"  # xcrun -f/--find TOOL: looks a tool up and runs nothing
SHELL, EDIT, KFLAG, REFUSE, OPT, ATTACHED, EXEC, PLAY, SHMODE = ("SHELL", "EDIT", "KFLAG", "REFUSE", "OPT", "ATTACHED",
                                                                "EXEC", "PLAY", "SHMODE")
VALUE_KINDS = {V, W, R, D, C, U, NV, S, PATHDIR, ENVFILE, SPLIT}
HELP = "--help --version"  # print and exit (C-m1): the runner runs nothing
FILE_OPS = {W: "write", R: "read", D: "write-dir"}
NAME_EQ = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


class Refused(Exception):
    pass


class Parsed(object):
    """outcome: unwrap | none | shell | refused | next (busybox: the applet is the next program) | env-S |
    sudo-shell. `end`: the payload's first word (unwrap, next) or the first word after the options (sudo-shell)."""

    def __init__(self, outcome="unwrap", end=None):
        self.outcome = outcome
        self.end = end
        self.files = []     # (Word, op) with op write | read | write-dir
        self.chdirs = []    # run-folder Words (C), in order
        self.env = []       # ("clear",) | ("set", name, Word) | ("unset", name or None) | ("unknown",)
        self.effect = "none"
        self.flags = set()  # path-modified
        self.shell = None   # [Word] whose words, joined with one space, are the shell text
        self.reason = None


class Spec(object):
    def __init__(self, name, opts, operands="argv", dashdash=True, legacy_num=False, dyn_operand=False,
                 any_long_value=False, bare_optional_refused=False, single_dash_long=False, numeric=(), prefixes=()):
        self.name = name
        self.opts = opts  # "-x" / "--name" -> kind
        self.operands = operands
        self.dashdash = dashdash
        self.legacy_num = legacy_num  # nice -5, --5, -+5
        self.dyn_operand = dyn_operand  # timeout $T cmd: a dynamic word where an option may stand is the DURATION
        self.any_long_value = any_long_value  # npx: any other --name=value is a value
        self.bare_optional_refused = bare_optional_refused  # xargs --max-lines 1 …: refused (BSD has no such option)
        self.single_dash_long = single_dash_long  # xcrun: -sdk, -find, … are its long options
        # value options that take a number or a duration (the §1.2 dropped-value rule)
        self.numeric = set(numeric.split() if isinstance(numeric, str) else numeric)
        # long options read from any unique start, with any number of dashes and in any case (npm's nopt: `--c=…`,
        # `---cal …` are --call; review 3 bypass M1)
        self.prefixes = tuple(prefixes)

    def long_name(self, name):
        """The long option `name` (`--x`, before any `=`) stands for: one of `prefixes` it starts, else itself."""
        if self.prefixes and name not in self.opts:
            base = name.lstrip("-").lower()
            for full in self.prefixes:
                if base and full[2:].startswith(base):
                    return full
        return name


def _o(*groups):
    out = {}
    for kind, names in groups:
        for n in names.split():
            out[n] = kind
    return out


def _spec(name, *groups, **kw):
    return Spec(name, _o(*groups), **kw)


SPECS = {}


def _add(spec, *aliases):
    for n in (spec.name,) + aliases:
        SPECS[n] = spec


_add(_spec("env", (F, "-0 -v --null --debug --list-signal-handling"), (CLEAR, "-i - --ignore-environment"),
           (OPT, "--block-signal --default-signal --ignore-signal"), (V, "-a --argv0"), (U, "-u --unset"),
           (C, "-C --chdir"), (PATHDIR, "-P"), (ENVFILE, "--env0-from"), (SPLIT, "-S --split-string"), (N, HELP),
           operands="env"))
_add(_spec("nohup", (N, HELP), operands="argv"))
_add(_spec("nice", (V, "-n --adjustment"), (N, HELP), legacy_num=True, numeric="-n --adjustment"), "gnice")
_add(_spec("timeout", (F, "-f -p -v --foreground --preserve-status --verbose"),
           (V, "-k --kill-after -s --signal"), (N, HELP), operands="timeout", dyn_operand=True,
           numeric="-k --kill-after"), "gtimeout")
_add(_spec("stdbuf", (V, "-i -o -e --input --output --error"), (N, HELP)), "gstdbuf")
_add(_spec("time", (F, "-a -l -h -p -q -v --append --portability --quiet --verbose"), (V, "-f --format"),
           (W, "-o --output"), (N, HELP)), "gtime")
_add(_spec("caffeinate", (F, "-d -i -m -s -u"), (V, "-t -w"), numeric="-t -w"))
_add(_spec("chronic", (F, "-e -v")))
_add(_spec("unbuffer", (F, "-p")))
_add(_spec("ionice", (F, "-t --ignore"), (V, "-c --class -n --classdata"), (NV, "-p --pid -P --pgid -u --uid"),
           (N, "-h -V " + HELP), numeric="-n --classdata"))
_add(_spec("setsid", (F, "-c --ctty -f --fork -w --wait"), (N, "-h -V " + HELP)))
_add(_spec("flock", (F, "-s --shared -x -e --exclusive -u --unlock -n --nb --nonblock -o --close -F --no-fork "
                        "--verbose"), (V, "-w --wait --timeout -E --conflict-exit-code"), (N, "-h -V " + HELP),
           operands="flock", numeric="-w --wait --timeout -E --conflict-exit-code"))
_add(_spec("lockf", (F, "-k -n -s -w"), (V, "-t"), operands="lockf", numeric="-t"))
_add(Spec("arch", {}, operands="arch"))
# xcrun reads its long options with one dash too (-sdk, -find, -show-sdk-path); -f/--find looks a tool up
_add(_spec("xcrun", (F, "-v --verbose -l --log -n --no-cache -r --run -k --kill-cache"), (V, "--sdk --toolchain"),
           (FIND, "-f --find"), (N, "-h --help --version --show-sdk-path --show-sdk-version --show-sdk-build-version "
                                    "--show-sdk-platform-path --show-sdk-platform-version"), operands="xcrun",
           single_dash_long=True))
_add(_spec("sandbox-exec", (V, "-n -p -D"), (R, "-f")))
_add(_spec("taskpolicy", (F, "-x -X -b -B -a -s"), (V, "-d -g -c -t -l -S -P -m -j"), (NV, "-p")))
_add(_spec("sudo", (F, "-A -b -H -n -P -S -B -N --askpass --background --set-home --non-interactive "
                       "--preserve-groups --stdin --bell --no-update"), (KEEP, "-E"), (OPT, "--preserve-env"),
           (V, "-u --user -g --group -C --close-from -p --prompt -r --role -t --type -T --command-timeout -U "
               "--other-user -c --login-class"), (C, "-D --chdir"), (SHELL, "-s --shell -i --login"),
           (EDIT, "-e --edit"), (N, "-l --list -v --validate -V --version -K --remove-timestamp"), (KFLAG, "-k"),
           (REFUSE, "-h -R --chroot"), operands="sudo"))
_add(_spec("doas", (F, "-n -L"), (V, "-u"), (SHELL, "-s"), (NV, "-C"), operands="sudo"))
_add(_spec("script", (F, "-a -d -e -F -f -k -q -r --append --flush --quiet --return"),
           (V, "-m --logging-format -o --output-limit -E --echo"),
           (W, "-I --log-in -O --log-out -B --log-io -T --log-timing --timing"), (ATTACHED, "-t"), (S, "-c --command"),
           (PLAY, "-p"), (N, "-h -V " + HELP), operands="script"))
_add(_spec("watch", (F, "-b -c -C -e -g -p -r -t -w --beep --color --no-color --errexit --chgexit --precise "
                        "--no-rerun --no-title --no-wrap"), (EXEC, "-x --exec"), (OPT, "-d --differences"),
           (V, "-n --interval -q --equexit"), (D, "-s --shotsdir"), (N, "-h -v " + HELP), operands="watch"))
_add(_spec("busybox", (N, "--list --help"), operands="busybox", dashdash=False), "toybox")

XARGS = _spec("xargs", (F, "-0 -o -p -r -t -x --null --open-tty --interactive --no-run-if-empty --verbose --exit "
                           "--show-limits"),
              (V, "-d --delimiter -E -I -J -L -n --max-args -P --max-procs -R -S -s --max-chars --process-slot-var"),
              (R, "-a --arg-file"), (OPT, "-e -i -l --eof --replace --max-lines"), (N, HELP), operands="xargs",
              bare_optional_refused=True, numeric="-L -n --max-args -P --max-procs -R -S -s --max-chars")
NPX = _spec("npx", (F, "-y --yes --no --no-install --ignore-existing -q --quiet --silent --bun --workspaces "
                       "--include-workspace-root --prefer-offline --prefer-online --offline"),
            (V, "-p --package -w --workspace --prefix --registry --cache --userconfig --loglevel"), (S, "-c --call"),
            (N, "-v -h " + HELP), operands="package", any_long_value=True, prefixes=("--call",))
PNPM_EXEC = _spec("pnpm-exec", (F, "-s --silent -r --recursive --parallel"), (V, "--package --filter"),
                  (SHMODE, "-c --shell-mode"), operands="package")
YARN_EXEC = Spec("yarn-exec", {}, operands="joined", dashdash=False)
PACKAGE_RUNNERS = {"npx": NPX, "bunx": NPX, "pnpx": NPX}
PACKAGE_SUBS = {("npm", "exec"): NPX, ("npm", "x"): NPX, ("bun", "x"): NPX, ("pnpm", "dlx"): PNPM_EXEC,
                ("pnpm", "exec"): PNPM_EXEC, ("yarn", "exec"): YARN_EXEC, ("yarn", "dlx"): NPX}

# Refused always (user, root or namespace changes the guard cannot follow; programs that run commands from text or
# argv the guard does not model). A tuple names the subcommands or options that run commands (only those are refused).
REFUSED = {"su": None, "runuser": None, "sg": None, "chroot": None, "unshare": None, "nsenter": None, "setpriv": None,
           "chrt": None, "taskset": None, "systemd-run": None, "expect": None, "tclsh": None, "wish": None, "m4": None,
           "dc": None, "ssh-agent": None, "screen": None, "tmux": None, "hyperfine": None, "uv": ("run",),
           "bundle": ("exec",), "direnv": ("exec",), "mise": ("exec", "x"), "leaks": ("--atExit",),
           "dtrace": ("-c",), "lldb": None, "launchctl": ("submit",), "at": None, "batch": None, "crontab": None,
           "zargs": None, "zmv": None, "zcp": None, "zln": None}
ARCH_FLAGS = ("-i386", "-x86_64", "-x86_64h", "-arm64", "-arm64e", "-32", "-64")


def lookup(key):
    """The Spec for a program key (NFC + casefold of the basename), busybox.* and busybox-* included."""
    spec = SPECS.get(key)
    if spec is None and key and (key.startswith("busybox.") or key.startswith("busybox-")):
        spec = SPECS["busybox"]
    return spec


def wrapper_name(spec, key):
    return "toybox" if key == "toybox" else spec.name


def refused_reason(key, words):
    """Why a program of the refused list is refused here, or None. `words`: its arguments."""
    if key not in REFUSED:
        return None
    subs = REFUSED[key]
    if subs is None:
        return "%s runs commands the guard does not follow" % key
    vals = [w.value for w in words]
    if any(v is None for v in vals):
        return "%s with a word the guard cannot read" % key
    for v in vals:
        if v in subs or (key == "leaks" and _leaks_at_exit(v)) or \
                (key == "dtrace" and v.startswith("-") and not v.startswith("--") and "c" in v[1:]):
            return "%s %s runs a command the guard does not follow" % (key, subs[0])
    if key == "leaks" and "--" in vals[:-1]:
        return "leaks -- runs a command the guard does not follow"
    return None


def _leaks_at_exit(v):
    """leaks' -atExit in any spelling it accepts: one or two dashes, any case, a start of it (review 3 bypass M2)."""
    base = v.lstrip("-").partition("=")[0].lower()
    return v.startswith("-") and len(base) >= 2 and ("atexit".startswith(base) or base.startswith("atexit"))


# ---- the reader ----

def _part(w, text):
    """The value part of an option word (`--chdir=stu?io`, `-Cs*`): literal, a wildcard when the word has one (fail
    closed: the guard does not track which characters were quoted)."""
    out = Word.lit(text)
    if w.glob and any(ch in text for ch in "*?["):
        k = min(text.find(ch) for ch in "*?[" if ch in text)
        out.glob, out.glob_base = True, text[:text.rfind("/", 0, k) + 1]
        out.glob_walk, out.extglob = False, getattr(w, "extglob", False)
    return out


def read(spec, words, i):
    """([(kind, option, value Word or None)], j): the options from words[i], j the first operand. A SPLIT option
    (env -S) ends the reading (its value and the remaining words are the split string)."""
    out = []
    j, n = i, len(words)
    while j < n:
        w = words[j]
        v = w.value
        if v is None:
            if spec.dyn_operand:
                break
            raise Refused("a word the guard cannot read where an option may stand (%s)" % w.raw)
        if v == "--" and spec.dashdash:
            return out, j + 1
        if v == "-":
            if "-" not in spec.opts:
                break
            out.append((spec.opts["-"], v, None))
            j += 1
            continue
        if not v.startswith("-"):
            break
        if spec.legacy_num and re.fullmatch(r"-[+-]?\d+", v):
            out.append((F, v, None))
            j += 1
            continue
        if spec.single_dash_long and not v.startswith("--") and len(v) > 2 and "-" + v.partition("=")[0] in spec.opts:
            v = "-" + v  # xcrun -sdk, -find, -show-sdk-path
        if v.startswith("--"):
            name, eq, val = v.partition("=")
            name = spec.long_name(name)
            k = spec.opts.get(name)
            if k is None:
                if spec.any_long_value and eq and len(name) > 2:
                    out.append((V, name, _part(w, val)))
                    j += 1
                    continue
                raise Refused("unknown option %s" % name)
            if k in VALUE_KINDS:
                if eq:
                    out.append((k, name, _part(w, val)))
                    j += 1
                elif j + 1 < n:
                    out.append((k, name, words[j + 1]))
                    j += 2
                else:
                    raise Refused("%s without its value" % name)
                if k == SPLIT:
                    return out, j
                continue
            if k == OPT:
                if not eq and spec.bare_optional_refused and j + 1 < n:
                    raise Refused("%s without =VALUE followed by a word (implementations read it differently)" % name)
                out.append((F, name, Word.lit(val) if eq else None))
                j += 1
                continue
            if eq:
                raise Refused("%s takes no value" % name)
            out.append((k, name, None))
            j += 1
            continue
        took, c, stop = 0, 1, False
        while c < len(v):
            opt = "-" + v[c]
            k = spec.opts.get(opt)
            if k is None:
                raise Refused("unknown option %s" % opt)
            rest = v[c + 1:]
            if k in VALUE_KINDS:
                if rest:
                    out.append((k, opt, _part(w, rest)))
                elif j + 1 < n:
                    out.append((k, opt, words[j + 1]))
                    took = 1
                else:
                    raise Refused("%s without its value" % opt)
                stop = k == SPLIT
                break
            if k == OPT:
                out.append((F, opt, Word.lit(rest) if rest else None))
                break
            if k == ATTACHED:
                if not rest:
                    raise Refused("%s with a separate value (BSD reads a time, util-linux a file)" % opt)
                out.append((W, opt, Word.lit(rest)))
                break
            out.append((k, opt, None))
            c += 1
        j += 1 + took
        if stop:
            return out, j
    return out, j


def _env_word(w):
    """("set", name, value Word) for a NAME=VALUE word (the value may be dynamic), else None."""
    if w.value is not None:
        if NAME_EQ.match(w.value):
            name, _, val = w.value.partition("=")
            return ("set", name, Word.lit(val))
        return None
    if NAME_EQ.match(w.skeleton or ""):
        name, _, val = w.skeleton.partition("=")
        return ("set", name, Word(w.raw, None, dynamic=True, dyn=w.dyn, skeleton=val))
    return None


def _apply(p, opts):
    """Options into the outcome; True when an option says the runner runs nothing (N)."""
    none = False
    for k, opt, val in opts:
        if k in FILE_OPS:
            if val.value is None:
                raise Refused("a file the guard cannot read (%s %s)" % (opt, val.raw))
            p.files.append((val, FILE_OPS[k]))
        elif k == C:
            p.chdirs.append(val)
        elif k == U:
            p.env.append(("unset", val.value))
        elif k == CLEAR:
            p.env.append(("clear",))
            p.effect = "env-clear"
        elif k == PATHDIR:
            p.flags.add("path-modified")
        elif k == ENVFILE:
            if val.value is None:
                raise Refused("a file the guard cannot read (%s %s)" % (opt, val.raw))
            p.files.append((val, "read"))
            p.env.append(("unknown",))
        elif k == REFUSE:
            raise Refused("%s is not accepted (help alone or a host with a value; a root change)" % opt)
        elif k in (N, NV, EDIT, PLAY):
            none = True
    return none


def _kinds(opts):
    return {k for k, _o, _v in opts}


def _argv(p, words, j, none):
    if none:
        if j < len(words):
            raise Refused("an option that runs nothing, followed by a command")
        p.outcome = "none"
        return p
    if j >= len(words):
        p.outcome = "none"
        return p
    p.end = j
    return p


def _lock_operand(p, words, j, isdir, op_name):
    """flock/lockf LOCK: written (O_CREAT); an existing folder is read; all digits with no further word: the fd form
    (runs nothing). Returns the index after it, or None for the fd form."""
    if j >= len(words):
        p.outcome = "none"
        return None
    w = words[j]
    if w.value is None:
        raise Refused("a %s the guard cannot read (%s)" % (op_name, w.raw))
    if w.value.isdigit() and j + 1 == len(words):
        p.outcome = "none"
        return None
    p.files.append((w, "read" if isdir(w.value) else "write"))
    return j + 1


def _joined(p, ws):
    p.outcome = "shell"
    p.shell = list(ws)
    return p


def parse(spec, words, i, isdir=lambda v: False):
    """Read the runner whose name is words[i-1] (its arguments start at words[i]). Always returns a Parsed; a
    refusal is outcome "refused" with a reason."""
    try:
        return _parse(spec, words, i, isdir)
    except Refused as e:
        p = Parsed("refused")
        p.reason = str(e)
        return p


def _parse(spec, words, i, isdir):
    p = Parsed()
    if spec.operands == "arch":
        return _arch(p, words, i)
    if spec.operands == "joined":
        if i >= len(words):
            p.outcome = "none"
            return p
        return _joined(p, words[i:])
    opts, j = read(spec, words, i)
    kinds = _kinds(opts)
    mode = spec.operands
    if mode == "env":
        if SPLIT in kinds:
            _apply(p, [o for o in opts if o[0] != SPLIT])
            sval = [v for k, _o, v in opts if k == SPLIT][0]
            p.outcome = "env-S"
            p.shell = [sval] + list(words[j:])
            return p
        none = _apply(p, opts)
        if p.effect != "env-clear":
            p.effect = "env-ops"
        while j < len(words):
            ew = _env_word(words[j])
            if ew is None:
                break
            p.env.append(ew)
            j += 1
        return _argv(p, words, j, none)
    if mode == "timeout":
        if _apply(p, opts):
            return _argv(p, words, j, True)  # --help, --version
        if j >= len(words):
            p.outcome = "none"
            return p
        return _argv(p, words, j + 1, False)
    if mode == "flock":
        if _apply(p, opts):
            return _argv(p, words, j, True)  # --help, --version
        k = _lock_operand(p, words, j, isdir, "lock file")
        if k is None:
            return p
        if k < len(words) and words[k].value is not None and words[k].value.startswith("-"):
            if words[k].value not in ("-c", "--command"):
                raise Refused("%s after the lock file" % words[k].value)
            if len(words) != k + 2:
                raise Refused("flock -c takes exactly one command string")
            return _joined(p, [words[k + 1]])
        if k < len(words) and words[k].value is None:
            raise Refused("a word the guard cannot read after the lock file (%s)" % words[k].raw)
        return _argv(p, words, k, False)
    if mode == "lockf":
        _apply(p, opts)
        k = _lock_operand(p, words, j, isdir, "lock file")
        if k is None:
            return p
        return _argv(p, words, k, False)
    if mode == "xcrun":
        none = _apply(p, opts)
        p.flags.add("path-modified")  # the tool comes from the developer folder
        if FIND in kinds:  # xcrun -f TOOL: prints the tool's path
            if len(words) - j != 1:
                raise Refused("xcrun --find takes one tool name")
            p.outcome = "none"
            return p
        return _argv(p, words, j, none)
    if mode == "sudo":
        return _sudo(p, opts, words, j)
    if mode == "script":
        return _script(p, opts, words, j)
    if mode == "watch":
        if _apply(p, opts):
            return _argv(p, words, j, True)  # --help, --version
        if j >= len(words):
            p.outcome = "none"
            return p
        if EXEC in kinds:
            p.end = j
            return p
        return _joined(p, words[j:])
    if mode == "busybox":
        none = _apply(p, opts)
        if none or j >= len(words):
            return _argv(p, words, j, True)
        p.outcome = "next"
        p.end = j
        return p
    if mode == "xargs":
        if _apply(p, [o for o in opts if o[0] != R]):  # -a FILE: the input (fed_inputs reads it)
            return _argv(p, words, j, True)  # --help, --version
        p.end = j
        return p
    if mode == "package":
        if _apply(p, opts):
            return _argv(p, words, j, True)  # --help, --version
        if S in kinds:
            if j < len(words):
                raise Refused("words after %s's command string" % spec.name)
            return _joined(p, [v for k, _o, v in opts if k == S])
        if SHMODE in kinds:
            if j >= len(words):
                p.outcome = "none"
                return p
            return _joined(p, words[j:])
        return _argv(p, words, j, False)
    none = _apply(p, opts)
    return _argv(p, words, j, none)


def _sudo(p, opts, words, j):
    kinds = _kinds(opts)
    _apply(p, [o for o in opts if o[0] not in (N, NV, EDIT)])
    keep = KEEP in kinds or any(o == "--preserve-env" for _k, o, _v in opts)
    if not keep:
        p.env.insert(0, ("clear",))
    p.effect = "user-change" if keep else "env-clear"
    if SHELL in kinds:
        p.outcome = "sudo-shell"
        p.end = j
        return p
    if EDIT in kinds:
        for w in words[j:]:
            if w.value is None:
                raise Refused("a file the guard cannot read (%s)" % w.raw)
            p.files.append((w, "write"))
        p.outcome = "none"
        return p
    if kinds & {N, NV}:
        return _argv(p, words, j, True)
    while j < len(words):  # sudo takes VAR=value words before the command
        ew = _env_word(words[j])
        if ew is None:
            break
        p.env.append(ew)
        j += 1
    return _argv(p, words, j, False)


def _script(p, opts, words, j):
    kinds = _kinds(opts)
    if N in kinds:  # -h, -V, --help, --version
        return _argv(p, words, j, True)
    _apply(p, [o for o in opts if o[0] != PLAY])
    if PLAY in kinds:  # BSD playback: reads FILE, runs nothing
        if j >= len(words) or len(words) > j + 1 or words[j].value is None:
            raise Refused("script -p takes exactly one readable file")
        p.files.append((words[j], "read"))
        p.outcome = "none"
        return p
    if j < len(words) and words[j].value is None:
        raise Refused("a typescript file the guard cannot read (%s)" % words[j].raw)
    fw = words[j] if j < len(words) else Word.lit("typescript")
    p.files.append((fw, "write"))
    if S in kinds:
        if len(words) > j + 1:
            raise Refused("words after script's file with -c")
        return _joined(p, [v for k, _o, v in opts if k == S])
    child = j + 1
    if child >= len(words):
        raise Refused("script without a command runs a shell on its input")
    if words[child].value is None or words[child].value.startswith("-"):
        raise Refused("script's command word is not a program the guard can read (%s)" % words[child].raw)
    p.end = child
    return p


def _arch(p, words, i):
    """arch (macOS): not getopt and no clusters."""
    j, n, none = i, len(words), False
    while j < n:
        v = words[j].value
        if v is None:
            raise Refused("a word the guard cannot read where an option may stand (%s)" % words[j].raw)
        if v in ARCH_FLAGS:
            j += 1
        elif v == "-c":
            p.env.append(("clear",))
            p.effect = "env-clear"
            j += 1
        elif v in ("-arch", "-d", "-e"):
            if j + 1 >= n:
                raise Refused("%s without its value" % v)
            val = words[j + 1]
            if v == "-d":
                p.env.append(("unset", val.value))
            elif v == "-e":
                ew = _env_word(val)
                p.env.append(ew if ew is not None else ("unknown",))
            j += 2
        elif v == "-h":
            none = True
            j += 1
        elif v == "--":
            j += 1
            break
        elif v.startswith("-"):
            raise Refused("unknown option %s" % v)
        else:
            break
    return _argv(p, words, j, none)


PACKAGE_PROGS = ("npm", "pnpm", "yarn")  # options may stand before the subcommand (bun's are its own: `bun -e`)
# npm reads its configuration from npm_config_* variables too (any case): npm_config_call is --call
NPM_CALL_VARS = ("npm_config_call",)


def _subcommand(words):
    """(index of the subcommand word, its option words) for npm, pnpm, yarn and bun: options may stand before the
    subcommand (`npm --call='…' exec`, `npm --prefix x exec …`); None when a word there cannot be read."""
    i, opts = 1, []
    value_opts = {n for sp in (NPX, PNPM_EXEC) for n, k in sp.opts.items() if k in VALUE_KINDS}
    while i < len(words):
        v = words[i].value
        if v is None:
            return None, opts
        if v == "--" or not v.startswith("-") or v == "-":
            break
        opts.append(words[i])
        if (v in value_opts or "=" not in v and v.startswith("--") and NPX.long_name(v) == "--call") and \
                i + 1 < len(words):
            opts.append(words[i + 1])
            i += 2
            continue
        i += 1
    return i, opts


def package(prog_key, words, env=None):
    """A package runner call (npx x, npm exec x, pnpm dlx x, yarn exec 'x', …): (Parsed, index of the package word)
    or (None, None) when the words are not one. `words`: the command's words (words[0] is the program); `env`: the
    variables in effect (EnvView.set, name -> Word), read for npm_config_call (M5)."""
    spec = PACKAGE_RUNNERS.get(prog_key)
    i, lead = 1, []
    if spec is None and prog_key in PACKAGE_PROGS:
        i, lead = _subcommand(words)
        if i is None:
            return None, None  # a word the guard cannot read before the subcommand (§3 reads it dropped too)
        if i < len(words) and words[i].value is not None:
            spec = PACKAGE_SUBS.get((prog_key, words[i].value))
        i += 1
    elif spec is None and len(words) > 1 and words[1].value is not None:
        spec = PACKAGE_SUBS.get((prog_key, words[1].value))  # bun x
        i = 2
    if spec is None:
        return None, None
    # options before the subcommand are the runner's own (npm --call='…' exec): read them with the rest
    ws = [words[0]] + lead + list(words[i:])
    p = parse(spec, ws, 1)
    if spec is NPX and p.outcome in ("unwrap", "none") and env:
        call = [w for n, w in env.items() if n.lower() in NPM_CALL_VARS]
        if call:
            if p.outcome == "unwrap":
                p = Parsed("refused")
                p.reason = "npm_config_call set and a package named"
            else:
                p = _joined(Parsed(), [call[-1] if call[-1] is not None else
                                       Word("$npm_config_call", None, dynamic=True, skeleton="\0")])
    end = p.end
    if end is not None:
        end = end - 1 - len(lead) + i  # back to an index into `words`
    return p, end


def shell_words_text(ws):
    """(text or None, skeleton): the shell text of a payload's words joined with one space."""
    if all(w.value is not None for w in ws):
        t = " ".join(w.value for w in ws)
        return t, t
    return None, " ".join(w.skeleton for w in ws)


def number_refused(spec, opt, word):
    """Whether a runner certainly rejects `word` as the value of `opt` (an option that takes a number or a duration):
    then it runs nothing (the §1.2 rule for a reading whose dropped word was that option's value). Only a word with no
    digit that cannot start inf/nan is certain (M2, review 2): strtod reads leading blanks, hex floats (`0x1p1`) and
    more, so any other word may be a number and the refusal stays."""
    if opt not in spec.numeric or word is None or word.value is None:
        return False
    t = word.value.strip().lstrip("+-").lower()
    return not any(ch.isdigit() for ch in word.value) and not t.startswith(("inf", "nan"))


__all__ = ["SPECS", "XARGS", "REFUSED", "Parsed", "parse", "lookup", "package", "refused_reason", "number_refused"]
