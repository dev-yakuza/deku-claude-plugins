"""Command lines the guard does not read, hidden in zsh's tables, in options and in environment variables (G1 plan
§1.8, §1.9, §1.11): data and pure readers of argument values. walk records what it sees; judge decides (in a Studio
repository these are refused with G-OPAQUE)."""

import fnmatch
import re

# ---- §1.8: zsh's command, alias, function and option tables ----

# special parameters whose writes change which program, alias or function a name runs, or zsh's options
TABLE_NAMES = ("commands", "functions", "functions_source", "aliases", "galiases", "saliases", "builtins", "reswords",
               "nameddirs", "options", "fpath", "FPATH", "module_path", "MODULE_PATH")
_NAMES = "|".join(TABLE_NAMES) + r"|dis_[A-Za-z_]+"
TABLE_RE = re.compile(r"^(%s)(\[.*\])?$" % _NAMES, re.S)
TABLE_ASSIGN_RE = re.compile(r"^(%s)(\[.*\])?\+?=" % _NAMES, re.S)
# ${name::=…}, ${name:=…}, ${name=…} (also with a subscript), and any assigning form of the (P) flag
PARAM_ASSIGN_RE = re.compile(r"^\$\{(%s)(\[[^\]]*\])?(::=|:=|=)" % _NAMES)  # after the flag group
# after a (P) flag group: a name, a positional or special parameter (`${(P)1::=…}`: review 3 m1)
NAME_ASSIGN_RE = re.compile(r"^(\d+|[#@*$!?-]|[A-Za-z_][A-Za-z0-9_]*)(\[[^\]]*\])?(::=|:=|=)")

# zsh builtins (and module builtins) that write a parameter they are given by name (review 4 M3, review 5 M1)
TYPESET = ("typeset", "declare", "local", "export", "readonly", "integer", "float")
NAME_WRITERS = TYPESET + ("read", "vared", "getopts", "zparseopts", "zformat", "pcre_match", "zregexparse",
                          "sysread", "getln", "regexp-replace", "zstyle", "print", "printf", "set", "strftime",
                          "zstat", "stat")

# autoload and zmodload in a Studio repository (§1.8, reviews 3, 6 and 7)
AUTOLOAD_OK = ("compinit", "bashcompinit", "colors", "is-at-least", "add-zsh-hook", "vcs_info", "promptinit",
               "zmathfunc")
ZMODLOAD_OK = ("zsh/parameter", "zsh/mathfunc", "zsh/datetime", "zsh/zutil", "zsh/complist", "zsh/terminfo",
               "zsh/termcap", "zsh/langinfo", "zsh/regex", "zsh/pcre")


def table_word(value):
    """Whether a word (after quote removal) names a table: `commands`, `commands[ls]`, `commands[ls]=/bin/rm`."""
    if value is None:
        return False
    return bool(TABLE_RE.match(value) or TABLE_ASSIGN_RE.match(value))


def _short_flags(vals):
    out = set()
    for v in vals:
        if v and v[0] in "-+" and len(v) > 1 and not v.startswith("--"):
            out |= set(v[1:])
    return out


# the option letter that takes the name of the parameter a builtin writes (`print -v NAME`, `set -A NAME`, …); the
# name may stand attached to it (`print -vNAME`, `set -Acommands`, `strftime -s'commands[ls]'`: M3, review 2)
NAME_OPTION = {"print": "v", "printf": "v", "set": "A", "strftime": "s", "zstat": "AH", "stat": "AH",
               "zparseopts": "Aa", "pcre_match": "av", "zformat": "", "read": ""}


def attached_names(prog, vals):
    """The texts attached to the name-taking option of `prog` (`print -rvNAME` → NAME), in a cluster too."""
    letters = NAME_OPTION.get(prog, "")
    out = []
    for v in vals:
        if not v or v[0] not in "-+" or len(v) < 3 or v.startswith("--"):
            continue
        for k, ch in enumerate(v[1:], 1):
            if ch in letters:
                if v[k + 1:]:
                    out.append(v[k + 1:])
                break
    return out


def name_writer(prog, vals):
    """Whether `prog vals…` is a builtin writing a parameter named by one of its words (§1.8)."""
    if prog in ("print", "printf"):
        return "v" in _short_flags(vals)
    if prog == "set":
        return any(v and v[:2] in ("-A", "+A") for v in vals)
    if prog == "strftime":
        return "s" in _short_flags(vals)
    if prog in ("zstat", "stat"):
        return bool(_short_flags(vals) & set("AH"))
    return prog in NAME_WRITERS


def has_short(vals, letters):
    return bool(_short_flags([v for v in vals if v is not None]) & set(letters))


NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def written_names(prog, vals):
    """The parameter names a name-writing builtin's words may name (M6): every literal word that is a name, the name
    before a subscript or read's `?prompt`, and a zparseopts spec's target after `=`; for `set`, the name after
    -A/+A."""
    att = [re.split(r"[\[?]", a, maxsplit=1)[0] for a in attached_names(prog, [v for v in vals if v is not None])]
    if prog == "set":
        return [vals[i + 1] for i, v in enumerate(vals[:-1]) if v in ("-A", "+A") and vals[i + 1] is not None and
                NAME_RE.match(vals[i + 1])] + [a for a in att if NAME_RE.match(a)]
    out = [a for a in att if NAME_RE.match(a)]
    for v in vals:
        if v is None or v[:1] in ("-", "+") and len(v) > 1:
            continue
        for n in (re.split(r"[\[?]", v, maxsplit=1)[0], v.rsplit("=", 1)[-1] if "=" in v else None):  # read 'NAME?prompt'
            if n and NAME_RE.match(n) and n not in out:
                out.append(n)
    return out


PAIRS = {"(": ")", "[": "]", "{": "}", "<": ">"}


def _flag_group(r):
    """(letters, end) of the (…) flag group at the start of `r` (`${(…)…}`): the flag letters without the delimited
    arguments of g, j, l, r, s, Z, I and _ (`(s(x)e)`, `(l:3::e:)`, `(s{)}e)`: the closing `)` of the group is found
    past them, M8 review 2), and the index after the group. ([], 2) when there is no group; an unterminated group
    gives every character as a letter (fail closed)."""
    if not r.startswith("${("):
        return [], 2
    out, i = [], 3
    while i < len(r):
        ch = r[i]
        if ch == ")":
            return out, i + 1
        if ch in "gjlrsZI_" and i + 1 < len(r) and not r[i + 1].isalnum() and r[i + 1] != ")":
            d = r[i + 1]
            close = PAIRS.get(d, d)
            i += 2
            for _arg in range(3):  # l and r take up to three arguments (l:expr::string1::string2:)
                k = r.find(close, i)
                if k < 0:
                    return out + [ch] + list(r[i:]), len(r)
                i = k + 1
                if ch not in "lr" or i >= len(r) or r[i] != d:
                    break
                i += 1
            out.append(ch)
            continue
        out.append(ch)
        i += 1
    return out + list(r[3:]), len(r)


def _flag_letters(flags):
    """The letters of a flag group's text (without its parentheses)."""
    return _flag_group("${(" + flags + ")")[0]


def _starts(raw):
    """Every ${…} in `raw`, outermost first (nested forms: `${${(e)X}}`, `${Y:-${(e)X}}`, M12)."""
    i = raw.find("${")
    while i >= 0:
        yield raw[i:]
        i = raw.find("${", i + 2)


def paramx_problem(raw):
    """What a ${…} form (or one nested in it) does that the guard does not follow: "eval" ((e) flag), "prompt" ((%)
    flag), "table" (an assignment to one of zsh's tables, or any assigning (P) form), or None."""
    raw = raw or ""
    found = []
    for r in _starts(raw):
        flags, end = _flag_group(r)
        if "e" in flags:
            return "eval"
        after = "${" + r[end:]
        if PARAM_ASSIGN_RE.match(after) or ("P" in flags and NAME_ASSIGN_RE.match(r[end:])):
            found.append("table")
        elif "%" in flags:
            found.append("prompt")
    return "table" if "table" in found else found[0] if found else None


ASSIGN_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)(\[[^\]]*\])?(::=|:=|=)")


def paramx_assigned(raw):
    """The names `${NAME::=…}`, `${NAME:=…}`, `${NAME=…}` assign in `raw` (nested forms too)."""
    out = []
    for r in _starts(raw or ""):
        m = ASSIGN_RE.match("${" + r[_flag_group(r)[1]:])
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


VCS_INFO_CONTEXT = ":vcs_info:git:x:y"  # vcs_info reads its styles (`command`, `hooks`, …) under :vcs_info:*


def zstyle_problem(vals):
    """Why a `zstyle` call is refused in a Studio repository, or None: setting a style vcs_info reads (its `command`
    style names the program vcs_info runs; M13). Queries and deletions (-L -d -g -s -b -a -t -T -m) set nothing. Fail
    closed (review 2, M9): a pattern is safe only when its literal start (before any pattern character or backslash)
    already differs from vcs_info's context; `--` ends the options."""
    vals = list(vals)
    if vals and vals[0] == "--":
        vals = vals[1:]
    elif vals and vals[0] is not None and vals[0].startswith("-"):
        return None  # -e is refused before; the others read or delete
    if not vals or vals[0] is None:
        return "zstyle with a word the guard cannot read" if vals else None
    pat = vals[0]
    k = next((i for i, ch in enumerate(pat) if ch in "*?[]()|<>^~#\\"), len(pat))
    lit = pat[:k]
    if VCS_INFO_CONTEXT.startswith(lit) or lit.startswith(":vcs_info:"):
        return "zstyle %s (vcs_info runs the commands its styles name)" % pat
    return None


def autoload_problem(vals):
    """Why an `autoload` call is refused in a Studio repository, or None (only the allowlist may be loaded)."""
    names = [v for v in vals if v is None or not v.startswith(("-", "+"))]
    for v in names:
        if v is None:
            return "autoload of a name the guard cannot read"
        if "/" in v:
            return "autoload of a file by its path (%s)" % v
        if v not in AUTOLOAD_OK:
            return "autoload %s (only %s may be loaded in a Studio repository)" % (v, ", ".join(AUTOLOAD_OK))
    return None


def zmodload_problem(vals):
    """Why a `zmodload` call is refused in a Studio repository, or None."""
    flags = set()
    names = []
    for v in vals:
        if v is None:
            return "zmodload of a module the guard cannot read"
        if v.startswith("-") and len(v) > 1:
            flags |= set(v[1:])
        else:
            names.append(v)
    if flags - set("ieLlu"):
        return "zmodload -%s" % "".join(sorted(flags - set("ieLlu")))
    if flags & set("eLl"):
        return None  # a query
    bad = [n for n in names if n not in ZMODLOAD_OK]
    if bad:
        return "zmodload %s (it adds builtins or parameters the guard does not model)" % bad[0]
    return None


# ---- §1.9: command-valued environment variables (any program) ----

EDITOR_VARS = ("EDITOR", "VISUAL", "GIT_EDITOR", "GIT_SEQUENCE_EDITOR")
PAGER_VARS = ("PAGER", "MANPAGER", "GIT_PAGER")
COMMAND_VARS = ("LESSOPEN", "LESSCLOSE", "GIT_EXTERNAL_DIFF", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_ASKPASS",
                "SSH_ASKPASS", "GIT_PROXY_COMMAND", "BROWSER", "VIMINIT", "EXINIT", "GVIMINIT", "VIM", "VIMRUNTIME",
                "MYVIMRC", "EXIFTOOL_HOME", "RSYNC_RSH", "RIPGREP_CONFIG_PATH")  # review 3 bypass m2
CMD_VARS = EDITOR_VARS + PAGER_VARS + COMMAND_VARS
EDITOR_OK = ("true", ":", "vi", "vim", "nano")
PAGER_OK = ("cat", "less", "more", "")
BOOLEAN = ("true", "false", "yes", "no", "on", "off", "1", "0")


def var_problem(name, value, path_modified):
    """Why setting `name` to `value` (None: not literal) is refused in a Studio repository, or None."""
    if name not in CMD_VARS:
        return None
    allowed = EDITOR_OK if name in EDITOR_VARS else PAGER_OK if name in PAGER_VARS else ()
    if value is None:
        return "%s set to a value the guard cannot read" % name
    if value not in allowed:
        return "%s=%s" % (name, value)
    if path_modified and value not in ("", ":", "true"):
        return "%s=%s with PATH changed in the same call" % (name, value)
    return None


# ---- §1.9: git ----

COMMAND_KEYS = ("core.hookspath", "alias.*", "hook.*", "include.path", "includeif.*", "core.editor", "core.pager",
                "pager.*", "core.sshcommand", "core.fsmonitor", "core.askpass", "core.gitproxy", "diff.external",
                "diff.*.command", "diff.*.textconv", "merge.*.driver", "filter.*.clean", "filter.*.smudge",
                "filter.*.process", "sequence.editor", "credential.helper", "credential.*.helper", "gpg.program",
                "gpg.*.program", "uploadpack.packobjectshook", "protocol.allow", "protocol.*.allow",
                "init.templatedir", "extensions.worktreeconfig", "remote.*.uploadpack", "remote.*.receivepack",
                "sendemail.*cmd", "sendemail.smtpserver", "sendemail.*.smtpserver", "*tool.*.cmd", "web.browser",
                "browser.*.cmd", "trailer.*.command", "trailer.*.cmd")  # trailer: runs a shell command (not in the plan)


def command_key(key, value=None):
    """Why setting the git key `key` to `value` may run a command line, or None. Editor and pager keys take the
    editor and pager values of the variables (`git -c core.editor=vi commit`, `git -c core.pager=cat log`). A key the
    guard cannot read (None) may be any. A URL value or a URL rewrite naming the ext:: transport runs a shell command
    (`remote.x.url=ext::…`, `url.ext::….insteadOf`, C-m2)."""
    if key is None:
        return "a -c the guard cannot read"
    k = key.lower()
    if "ext::" in k or (value is not None and value.lstrip().startswith("ext::")):
        return "%s=%s" % (key, value if value is not None else "…")
    if not any(fnmatch.fnmatchcase(k, p) for p in COMMAND_KEYS):
        return None
    if k in ("core.editor", "sequence.editor") and value in EDITOR_OK:
        return None
    if (k == "core.pager" or k.startswith("pager.")) and (value in PAGER_OK or (
            k.startswith("pager.") and value is not None and value.lower() in BOOLEAN)):
        return None
    return "%s=%s" % (key, value if value is not None else "…")


GIT_ENV_REFUSED = ("GIT_ALLOW_PROTOCOL", "GIT_PROTOCOL_FROM_USER", "GIT_TEMPLATE_DIR", "GIT_EXEC_PATH",
                   "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG", "HOME", "XDG_CONFIG_HOME")


GIT_ENV_JUDGED = GIT_ENV_REFUSED + ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_DIR",
                                   "GIT_WORK_TREE")


def watched_var(name):
    """A §1.9 variable: command-valued (any program) or one git's configuration routes read."""
    return name in CMD_VARS or name in GIT_ENV_JUDGED or bool(re.match(r"^GIT_CONFIG_(KEY|VALUE)_\d+$", name or ""))


def git_env_problems(env_set):
    """The git configuration routes in the environment a git command runs with (`cmd.env.set`: name -> Word)."""
    out = []
    for name in GIT_ENV_REFUSED:
        if name in env_set:
            out.append(name)
    if "GIT_CONFIG_NOSYSTEM" in env_set:
        w = env_set["GIT_CONFIG_NOSYSTEM"]
        v = w.value if w is not None else None
        if v is None or v.lower() in ("", "0", "false", "no", "off"):
            out.append("GIT_CONFIG_NOSYSTEM=%s" % (v if v is not None else "…"))
    if "GIT_CONFIG_PARAMETERS" in env_set:
        w = env_set["GIT_CONFIG_PARAMETERS"]
        v = w.value if w is not None else None
        pairs = re.findall(r"'([^'=]*)'?=?'?([^']*)'", v or "")
        if v is None or not pairs or any(command_key(k, val) for k, val in pairs):
            out.append("GIT_CONFIG_PARAMETERS")
    for name, w in env_set.items():
        if re.match(r"^GIT_CONFIG_(KEY|VALUE)_\d+$", name) or name == "GIT_CONFIG_COUNT":
            if name.startswith("GIT_CONFIG_KEY_"):
                n = name[len("GIT_CONFIG_KEY_"):]
                key = w.value if w is not None else None
                vw = env_set.get("GIT_CONFIG_VALUE_" + n)
                val = vw.value if vw is not None else None
                if key is None or command_key(key, val):
                    out.append("%s=%s" % (name, key if key is not None else "…"))
    return out


def _short_has(v, letters):
    return v is not None and v.startswith("-") and not v.startswith("--") and len(v) > 1 and \
        any(c in v[1:] for c in letters)


def long_option(v, names, exact=()):
    """Whether `v` is one of the long options `names` (`--name`, `--name=value`) or an abbreviation of one, as git's
    parse-options and getopt_long accept (M7, M10): a prefix of a listed name that is not itself another option of
    the program (`exact`: `--to` of send-email, `--tool` of mergetool). An ambiguous prefix fails closed (it is
    taken for the listed option; the program refuses it anyway)."""
    if v is None or not v.startswith("--"):
        return False
    name = v.partition("=")[0]
    if name in names:
        return True
    return len(name) > 2 and name not in exact and any(n.startswith(name) for n in names)


URL_SUBS = ("clone", "fetch", "pull", "push", "ls-remote", "remote", "submodule", "archive")


def git_option_problem(sub, args):
    """A git subcommand option (or operand) that runs a command line: the option's text, or None. `args`: the values
    after the subcommand (None for a dynamic word)."""
    vals = list(args)
    if sub in URL_SUBS:
        for v in vals:  # the ext:: transport runs a shell command: a URL operand or a URL-valued option (C-m2)
            if v is not None and (v.startswith("ext::") or (v.startswith("-") and "=" in v and
                                                            v.split("=", 1)[1].startswith("ext::"))):
                return v
    if sub == "rebase":
        for v in vals:
            if long_option(v, ("--exec",)) or _short_has(v, "x"):
                return v
    elif sub == "bisect":
        if vals[:1] == ["run"]:
            return "bisect run"
    elif sub == "difftool":
        for v in vals:
            if long_option(v, ("--extcmd",)) or _short_has(v, "x"):
                return v
    elif sub == "mergetool":
        for v in vals:
            if long_option(v, ("--tool-cmd",), exact=("--tool",)):
                return v
    elif sub == "submodule":
        if "foreach" in vals:
            return "submodule foreach"
    elif sub in ("fetch", "pull", "clone", "ls-remote", "remote"):
        for v in vals:
            if long_option(v, ("--upload-pack",)) or v == "-u" or (
                    sub in ("clone", "ls-remote") and _short_has(v, "u")):
                return v
    elif sub == "push":
        for v in vals:
            if long_option(v, ("--receive-pack", "--exec")):
                return v
    elif sub == "archive":
        for v in vals:
            if long_option(v, ("--exec",)):
                return v
    elif sub == "grep":
        for v in vals:
            if long_option(v, ("--open-files-in-pager",)) or _short_has(v, "O"):
                return v
    elif sub == "send-email":
        # Getopt::Long: long options with one dash too (`-sendmail-cmd=…`, `-smtp-s …`: review 2, M7)
        vals = ["-" + v if v is not None and v.startswith("-") and not v.startswith("--") and len(v) > 2 else v
                for v in vals]
        for i, v in enumerate(vals):
            if long_option(v, ("--sendmail-cmd", "--to-cmd", "--cc-cmd", "--header-cmd"), exact=("--to", "--cc")):
                return v
            if long_option(v, ("--smtp-server",)):
                val = v.split("=", 1)[1] if "=" in v else (vals[i + 1] if i + 1 < len(vals) else None)
                if val is None or "/" in val:
                    return v
    if sub in ("init", "clone"):
        for v in vals:
            if long_option(v, ("--template",)):
                return v
    return None


def config_pair(word):
    """(key, value) of a `key=value` word: the value None when it is not literal, the key None when the guard cannot
    read it (`-c $A`, `-c "$(…)"`: M9, C-M2)."""
    if word is None:
        return (None, None)
    if word.value is not None:
        k, _, val = word.value.partition("=")
        return (k, val)
    k, eq, _val = (word.skeleton or "").partition("=")
    if eq and k and "\0" not in k:
        return (k, None)
    return (None, None)


def _attached(word, prefix):
    """The word after `prefix` (`--config=…`, `-c…`) as a Word, its value or skeleton cut."""
    from .model import Word
    if word.value is not None:
        return Word.lit(word.value[len(prefix):])
    return Word(word.raw, None, dynamic=True, dyn=word.dyn, skeleton=(word.skeleton or "")[len(prefix):])


CLONE_VALUE_LETTERS = "cobuj"  # git clone's short options that take a value


def clone_configs(words):
    """(key, value) of `git clone -c k=v`, `--config k=v`, `--config=k=v` (abbreviations too); `words` are the
    clone's argument Words (config_pair: None for what the guard cannot read)."""
    out = []
    i = 0
    while i < len(words):
        w = words[i]
        t = w.value if w.value is not None else (w.skeleton or "")
        name = t.partition("=")[0]
        if t == "-c" or ("=" not in t and long_option(t, ("--config",))):
            out.append(config_pair(words[i + 1] if i + 1 < len(words) else None))
            i += 2
            continue
        if "=" in t and long_option(name, ("--config",)):
            out.append(config_pair(_attached(w, name + "=")))
        elif t.startswith("-") and not t.startswith("--") and len(t) > 1:
            # a short cluster (`-qc k=v`, `-qck=v`, `-nc …`: parse-options, review 2 M5): the letters before a value
            # letter are flags; -c takes the rest of the cluster or the next word
            for k, ch in enumerate(t[1:], 1):
                if ch not in CLONE_VALUE_LETTERS:
                    continue
                if ch == "c":
                    if t[k + 1:]:
                        out.append(config_pair(_attached(w, t[:k + 1])))
                    else:
                        out.append(config_pair(words[i + 1] if i + 1 < len(words) else None))
                if not t[k + 1:]:
                    i += 1  # the value is the next word
                break
        i += 1
    return out


CONFIG_VALUE_OPTS = ("--file", "-f", "--blob", "--type", "--default", "--comment", "--value")


def config_sets(args):
    """(key, value) pairs a `git config` call sets (None for an unreadable key or value); [] for reads and
    removals. ("*", None) when it may set anything (`--edit`)."""
    vals = list(args)
    if not vals:
        return []
    if vals[0] in ("set",):
        pos = [v for v in vals[1:] if v is None or not v.startswith("-")]
        return [(pos[0], pos[1] if len(pos) > 1 else None)] if pos else [("*", None)]
    if vals[0] in ("get", "list", "unset", "remove-section", "rename-section"):
        return []  # rename-section: config_renames
    if vals[0] == "edit":
        return [("*", None)]
    pos, read, unset = [], False, False
    i = 0
    while i < len(vals):
        a = vals[i]
        if a is None:
            pos.append(None)
        elif a in CONFIG_VALUE_OPTS:
            i += 2
            continue
        elif a in ("--edit", "-e"):
            return [("*", None)]
        elif a.startswith("--unset") or a in ("--remove-section", "--rename-section"):
            unset = True
        elif a in ("--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l") or \
                a.startswith(("--get", "--get-colors", "--get-color")):
            read = True
        elif not a.startswith("-"):
            pos.append(a)
        i += 1
    if read or unset or len(pos) < 2:
        return []
    return [(pos[0], pos[1])]


def config_renames(args):
    """The new section names of `git config --rename-section OLD NEW` / `git config rename-section OLD NEW` (None
    when the guard cannot read it): the keys move into NEW (M8)."""
    vals = list(args)
    i, pos, ren = 0, [], False
    while i < len(vals):
        a = vals[i]
        if a is not None and a in CONFIG_VALUE_OPTS:
            i += 2
            continue
        if a is not None and (a == "rename-section" and not pos and not ren or long_option(a, ("--rename-section",))):
            ren = True
        elif a is None or not a.startswith("-"):
            pos.append(a)
        i += 1
    if not ren:
        return []
    if len(pos) < 2:
        return [None]
    return [pos[1]]


def command_section(section):
    """Why a config section may hold keys that run command lines once renamed to it (`core`, `alias`, `diff.x`,
    `includeIf.onbranch:main`, `url.ext::…`), or None: some key `<section>.<name>` matches a command key (review 2,
    M6: the two-part patterns `includeif.*`, `hook.*` match whole sections)."""
    if section is None:
        return "a section the guard cannot read"
    sec = section.lower()
    if "ext::" in sec:
        return section
    for p in COMMAND_KEYS:
        last = p.rsplit(".", 1)[-1]
        if fnmatch.fnmatchcase(sec + "." + last.replace("*", "x"), p):
            return section
    return None


# ---- §1.9: other programs' command-valued options ----

SSH_OPTS = ("proxycommand", "localcommand", "knownhostscommand")


def _ssh_option(text):
    parts = re.split(r"\s*=\s*|\s+", text.strip(), maxsplit=1)
    key = parts[0].lower()
    val = parts[1] if len(parts) > 1 else ""
    if key in SSH_OPTS:
        return text
    if key == "permitlocalcommand" and val.lower() in ("yes", "true"):
        return text
    if key == "match" and "exec" in val.lower():
        return text
    return None


SSH_VALUE = set("bcDEeFIiJLlmOopQRSWw")


def program_option_problem(prog, vals):
    """A command-valued option of ssh/scp/sftp, rsync, tar, zip, sort, man or make: its text, or None."""
    if prog in ("ssh", "scp", "sftp"):
        i = 0
        while i < len(vals):
            v = vals[i]
            if v is None:
                i += 1
                continue
            if v.startswith("-") and not v.startswith("--") and len(v) > 1:
                for c, ch in enumerate(v[1:], 1):
                    if ch in "FS":
                        return v
                    if ch in SSH_VALUE:
                        rest = v[c + 1:]
                        val = rest if rest else (vals[i + 1] if i + 1 < len(vals) else None)
                        if ch == "o":
                            if val is None:
                                return v
                            hit = _ssh_option(val)
                            if hit:
                                return "-o " + hit
                        if not rest:
                            i += 1
                        break
            i += 1
        return None
    if prog == "rsync":
        for v in vals:
            if long_option(v, ("--rsh", "--rsync-path")) or _short_has(v, "e"):
                return v
        return None
    if prog in ("tar", "gtar", "bsdtar"):
        for i, v in enumerate(vals):
            if long_option(v, ("--use-compress-program", "--to-command", "--info-script", "--new-volume-script"),
                     exact=("--to-stdout",)):
                return v
            if long_option(v, ("--checkpoint-action",), exact=("--checkpoint",)):
                val = v.partition("=")[2] if "=" in v else (vals[i + 1] if i + 1 < len(vals) else "")
                if val is None or "exec" in val:  # `--checkpoint-action exec=…` (a separate value: review 2, M16)
                    return v if "=" in v else "%s %s" % (v, val if val is not None else "…")
            if _short_has(v, "IF"):
                return v
            if i == 0 and v is not None and re.fullmatch(r"[A-Za-z]+", v) and ("I" in v or "F" in v):
                return v  # old-style bundled letters (tar cIf …)
        return None
    if prog == "zip":
        for v in vals:
            if v is not None and (v.startswith("-TT") or long_option(v, ("--unzip-command",))):
                return v
        return None
    if prog == "sort":
        for v in vals:
            if long_option(v, ("--compress-program",)):
                return v
        return None
    if prog == "man":
        for v in vals:
            if v is not None and (long_option(v, ("--pager", "--html"), exact=("--path",)) or
                                  (v.startswith(("-P", "-H")) and not v.startswith("--"))):
                return v
        return None
    if prog in ("make", "gmake"):
        for i, v in enumerate(vals):
            if v is None:
                continue
            if re.match(r"^(SHELL|MAKESHELL|\.SHELLFLAGS)\+?:{0,2}=", v):
                return v
            f = None
            if "=" not in v and long_option(v, ("--file", "--makefile")) and i + 1 < len(vals):
                f = vals[i + 1]
            elif "=" in v and long_option(v, ("--file", "--makefile")):
                f = v.split("=", 1)[1]
            elif v.startswith("-") and not v.startswith("--") and len(v) > 1:
                # a short cluster (`-sf -`, `-kf /dev/stdin`, `-if-`: review 2, M15): -f takes the rest or the next
                # word; -C -I -o -W -E take one too; -j -l -O an attached one only
                for k, ch in enumerate(v[1:], 1):
                    if ch == "f":
                        f = v[k + 1:] or (vals[i + 1] if i + 1 < len(vals) else None)
                        break
                    if ch in "CIoWEjlO":
                        break
            if f is not None and f in ("-", "/dev/stdin", "/dev/fd/0"):
                return v if v.endswith(f) else "%s %s" % (v, f)
        return None
    return None
