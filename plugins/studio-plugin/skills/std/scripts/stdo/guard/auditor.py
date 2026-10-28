"""The external auditor's tool limits (m1-plan §7.4, D-M1-7 · J46): a call whose hook input says `agent_type` is
`std-auditor` (a plugin prefix `x:std-auditor` too) may only read. Write · Edit · MultiEdit · NotebookEdit and every
MCP tool are denied (the guard cannot tell an MCP tool that only reads); Bash passes only when every command is a
reader (protect.READ_ALLOW without `open`, git's reading subcommands, find without its writing actions), nothing is
redirected into a file but /dev/null, and nothing runs code the guard cannot read. The role's own template already
lists only Read, Grep and Glob; this is the guard's side of it, in every repository."""

from . import protect

ROLE = "std-auditor"
READERS = frozenset(protect.READ_ALLOW) - {"open"}
GIT_READERS = frozenset(["diff", "status", "log", "show", "ls-files", "rev-parse", "blame", "grep", "ls-tree",
                         "cat-file", "shortlog", "describe"])
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
RULE = "G-AUDIT"


def is_auditor(hook):
    at = hook.get("agent_type")
    return isinstance(at, str) and at.rsplit(":", 1)[-1] == ROLE


def _git_sub(argv):
    """git's subcommand, or None — also for a `-c` setting before it (it could name a program to run)."""
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "-c" or a.startswith("--config-env"):
            return None
        if a in ("-C", "--git-dir", "--work-tree"):
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a
    return None


ENV_RUNS = ("LESSOPEN", "LESSCLOSE")  # less runs these; GIT_* (but GIT_PAGER) can name programs or config (S3)


def _env_problem(c):
    for op in c.env.ops:
        name = op.name or ""
        if (name.startswith("GIT_") and name != "GIT_PAGER") or name in ENV_RUNS:
            return "it sets %s, which can make a reader run a program" % name
    return None


def _uniq_operands(argv):
    out, i = [], 1
    while i < len(argv):
        a = argv[i]
        if a in ("-f", "-s", "-w", "--skip-fields", "--skip-chars", "--check-chars"):
            i += 2
            continue
        if a == "--":
            out += argv[i + 1:]
            break
        if not (a.startswith("-") and a != "-"):
            out.append(a)
        i += 1
    return out


def _reader_problem(prog, argv):
    """Readers that can still write or run something (S3)."""
    if prog == "sort" and any(a == "-o" or a.startswith("--output") or
                              (a.startswith("-") and not a.startswith("--") and "o" in a[1:]) for a in argv[1:]):
        return "sort -o writes a file"
    if prog == "uniq" and len(_uniq_operands(argv)) >= 2:
        return "uniq with a second file writes it"
    if prog == "rg" and any(a in ("--pre", "--pre-glob", "-z", "--search-zip") or
                            a.startswith(("--pre=", "--pre-glob=")) for a in argv[1:]):
        return "rg --pre / --search-zip runs other programs"
    return None


def bash_problem(sc):
    """Why this scanned command is not read-only, or None."""
    if sc.status != "ok":
        return "the guard could not read the command (%s)" % (sc.reason or sc.status)
    if sc.opaque:
        return "it runs code the guard cannot read (%s)" % sc.opaque[0].kind
    for c in sc.commands:
        argv = c.argv
        if not argv or any(a is None for a in argv):
            return "a command word is not a plain value"
        prog = c.prog
        if prog == "git":
            sub = _git_sub(argv)
            if sub not in GIT_READERS or any(a == "--output" or a.startswith(("--output=", "--ext-diff", "--textconv"))
                                             for a in argv):
                return "git %s is not a reading git command" % (sub or "")
        elif prog == "find":
            if any(a in protect.FIND_WRITE for a in argv):
                return "find with an action that writes or runs"
        elif prog not in READERS:
            return "%s is not a reading command" % prog
        why = _env_problem(c) or _reader_problem(prog, argv)
        if why:
            return why
        for r in c.redirs:
            if r.mode in ("write", "append", "rw") and (r.target is None or r.target.value != "/dev/null"):
                return "a redirection writes a file"
    return None


def judge(ctx, tool, ti):
    """Deny through ctx when the auditor's call is not a read."""
    if tool in WRITE_TOOLS:
        ctx.deny(RULE, "the external auditor (std-auditor) only reads — %s is denied. Report findings instead." % tool)
    elif tool.startswith("mcp__"):
        ctx.deny(RULE, "the external auditor (std-auditor) uses no MCP tools (%s)." % tool)
    elif tool == "Bash":
        from . import scan as scan_command
        cmd = ti.get("command") if isinstance(ti, dict) else None
        if not isinstance(cmd, str):
            ctx.deny(RULE, "the external auditor's Bash call has no command.")
            return
        sc = scan_command(cmd, ctx.cwd, ctx.env, fs=ctx.fs)
        why = bash_problem(sc)
        if why:
            ctx.deny(RULE, "the external auditor (std-auditor) only reads: %s. Use Read, Grep and Glob." % why)
