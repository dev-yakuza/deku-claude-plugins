"""`setup.py doc [<name>]` (pilot-1 P6): print one of Studio's own documents — a command (commands/<name>.md) or a
shared rule (commands/atoms/<name>.md) — so the agent never opens the plugin folder with Read, which asks the person
on every file outside the working directories. Plugin-only and read-only: it writes nothing and needs no repository.

    setup.py doc                  every document's name with its first heading
    setup.py doc <name>           a header line, then the document with <<SKILL_DIR>> replaced by the skill folder
    setup.py doc s2v-syntax       s2v's script syntax (write-script/reference.md of this work tree's s2v, 0.0.25 P10)

A name is looked up in a table built from the files that exist (make, commands/make.md, _contract, atoms/_contract.md,
commands/atoms/_contract.md) — never joined from the argument. Exit: 0 printed · 2 unknown document or usage.
Pure apart from reading the documents (no processes): the guard imports NAMES to know which calls print a document.

`s2v-syntax` is a fixed name, not a file of the plugin: the repository is found by walking up from the working folder
for `.git` (no process), the s2v path comes from its machine.json, and the file is read only when it is a regular file
under the s2v folder (opened without following a link, the opened file the one its real path names) of at most
MAX_CHARS characters. Otherwise exit 2 with nothing printed."""

import json
import os
import stat
import sys

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.dirname(SCRIPTS)
COMMANDS = os.path.join(SKILL, "commands")
ATOMS = os.path.join(COMMANDS, "atoms")
PLUGIN_JSON = os.path.join(SKILL, "..", "..", ".claude-plugin", "plugin.json")
MARK = "<<SKILL_DIR>>"
S2V_SYNTAX = "s2v-syntax"
S2V_SYNTAX_REL = os.path.join(".claude", "skills", "write-script", "reference.md")
S2V_SYNTAX_TITLE = "s2v script syntax"
MAX_CHARS = 25000
NO_S2V = "no s2v path: run /std init or /std config"


def _md(folder):
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted(n[:-3] for n in names if n.endswith(".md") and os.path.isfile(os.path.join(folder, n)))


def table():
    """{spelling: (name, path relative to the skill folder)} for every document that exists."""
    out = {}
    for n in _md(COMMANDS):
        rel = "commands/%s.md" % n
        for k in (n, rel):
            out[k] = (n, rel)
    for n in _md(ATOMS):
        rel = "commands/atoms/%s.md" % n
        for k in (n, "atoms/%s.md" % n, rel):
            out[k] = (n, rel)
    return out


def names():
    """The documents' names: the commands, then the shared rules (atoms)."""
    return _md(COMMANDS) + _md(ATOMS)


NAMES = frozenset(names() + [S2V_SYNTAX])


def _version():
    try:
        with open(PLUGIN_JSON, encoding="utf-8") as f:
            return json.load(f).get("version") or "?"
    except (OSError, ValueError):
        return "?"


def skill_dir(script=None):
    """The skill folder as the person's command spelled it (abspath of setup.py's path, not its real path)."""
    script = script if script is not None else sys.argv[0]
    if script and os.path.basename(script) == "setup.py":
        return os.path.dirname(os.path.dirname(os.path.abspath(script)))
    return SKILL


def _command(skill):
    return 'python3 "%s/scripts/setup.py" doc' % skill


def _heading(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    return line.lstrip("#").strip()
    except OSError:
        pass
    return ""


def listing(skill):
    lines = ["# Studio documents (plugin %s). Print one with: %s <name> — never open them with Read."
             % (_version(), _command(skill))]
    tab = table()
    for n in names():
        rel = tab[n][1]
        lines.append("- %s — %s (%s)" % (n, _heading(os.path.join(SKILL, rel)), rel[len("commands/"):]))
    lines.append("- %s — %s (from this work tree's s2v)" % (S2V_SYNTAX, S2V_SYNTAX_TITLE))
    return "\n".join(lines) + "\n"


def render(name, skill):
    """The header line and the document `name` (a canonical name), <<SKILL_DIR>> replaced."""
    rel = table()[name][1]
    with open(os.path.join(SKILL, rel), encoding="utf-8") as f:
        body = f.read()
    head = ("# Studio document %s (%s · plugin %s). Other Studio documents named in it (commands/…, atoms/…): "
            "%s <name> — never open them with Read." % (name, rel, _version(), _command(skill)))
    return head + "\n" + body.replace(MARK, skill)


def repo_root(start):
    """The nearest folder at or above `start` holding `.git` (a folder, or a file in a worktree), or None."""
    d = os.path.abspath(start)
    while True:
        if os.path.lexists(os.path.join(d, ".git")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def s2v_syntax(cwd):
    """(the reference's text, None) · (None, a message for a missing s2v path) · (None, None) when the file is not
    a safe regular file under the s2v folder."""
    from .. import machine, paths  # lazily: the guard imports NAMES and must not load the rest
    repo = repo_root(cwd)
    if repo is None:
        return None, NO_S2V
    try:
        s2v = machine.s2v_path(repo)
    except paths.UnsafeLocal:
        return None, None
    if s2v is None:
        return None, NO_S2V
    p = os.path.join(s2v, S2V_SYNTAX_REL)
    root, real = os.path.realpath(s2v), os.path.realpath(p)
    if not real.startswith(root.rstrip(os.sep) + os.sep):
        return None, None
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)  # NONBLOCK: a FIFO never hangs the call
    except OSError:
        return None, None
    try:
        st = os.fstat(fd)
        rs = os.stat(real)
        if not stat.S_ISREG(st.st_mode) or (st.st_dev, st.st_ino) != (rs.st_dev, rs.st_ino):
            return None, None
        limit = MAX_CHARS * 4 + 1  # UTF-8: at most 4 bytes a character
        chunks, size = [], 0
        while size < limit:
            b = os.read(fd, limit - size)
            if not b:
                break
            chunks.append(b)
            size += len(b)
        text = b"".join(chunks).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None, None
    finally:
        os.close(fd)
    if len(text) > MAX_CHARS:
        return None, None
    return text, None


def main(args, script=None, out=None, err=None, cwd=None):
    out = out or sys.stdout
    err = err or sys.stderr
    skill = skill_dir(script)
    if not args:
        out.write(listing(skill))
        return 0
    if args == [S2V_SYNTAX]:
        text, why = s2v_syntax(cwd or os.getcwd())
        if text is None:
            if why:
                err.write("std doc: %s\n" % why)
            return 2
        out.write("# %s (the write-script reference of this work tree's s2v). Write the script with it.\n" %
                  S2V_SYNTAX_TITLE)
        out.write(text)
        return 0
    tab = table()
    if len(args) != 1 or args[0] not in tab:
        if len(args) != 1:
            err.write("std doc: one document name at most (setup.py doc <name>)\n")
        else:
            err.write("std doc: unknown document %s — one of: %s\n" % (args[0][:80], ", ".join(names() + [S2V_SYNTAX])))
        return 2
    out.write(render(tab[args[0]][0], skill))
    return 0
