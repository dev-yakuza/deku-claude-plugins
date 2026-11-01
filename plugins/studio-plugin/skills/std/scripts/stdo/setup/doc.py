"""`setup.py doc [<name>]` (pilot-1 P6): print one of Studio's own documents — a command (commands/<name>.md) or a
shared rule (commands/atoms/<name>.md) — so the agent never opens the plugin folder with Read, which asks the person
on every file outside the working directories. Plugin-only and read-only: it writes nothing and needs no repository.

    setup.py doc                  every document's name with its first heading
    setup.py doc <name>           a header line, then the document with <<SKILL_DIR>> replaced by the skill folder

A name is looked up in a table built from the files that exist (make, commands/make.md, _contract, atoms/_contract.md,
commands/atoms/_contract.md) — never joined from the argument. Exit: 0 printed · 2 unknown document or usage.
Pure apart from reading the documents (no processes): the guard imports NAMES to know which calls print a document."""

import json
import os
import sys

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.dirname(SCRIPTS)
COMMANDS = os.path.join(SKILL, "commands")
ATOMS = os.path.join(COMMANDS, "atoms")
PLUGIN_JSON = os.path.join(SKILL, "..", "..", ".claude-plugin", "plugin.json")
MARK = "<<SKILL_DIR>>"


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


NAMES = frozenset(names())


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
    return "\n".join(lines) + "\n"


def render(name, skill):
    """The header line and the document `name` (a canonical name), <<SKILL_DIR>> replaced."""
    rel = table()[name][1]
    with open(os.path.join(SKILL, rel), encoding="utf-8") as f:
        body = f.read()
    head = ("# Studio document %s (%s · plugin %s). Other Studio documents named in it (commands/…, atoms/…): "
            "%s <name> — never open them with Read." % (name, rel, _version(), _command(skill)))
    return head + "\n" + body.replace(MARK, skill)


def main(args, script=None, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    skill = skill_dir(script)
    if not args:
        out.write(listing(skill))
        return 0
    tab = table()
    if len(args) != 1 or args[0] not in tab:
        if len(args) != 1:
            err.write("std doc: one document name at most (setup.py doc <name>)\n")
        else:
            err.write("std doc: unknown document %s — one of: %s\n" % (args[0][:80], ", ".join(names())))
        return 2
    out.write(render(tab[args[0]][0], skill))
    return 0
