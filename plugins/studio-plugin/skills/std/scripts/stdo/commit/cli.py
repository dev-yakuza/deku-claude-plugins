"""check_commit.py — Studio's commit checks (M0e; m0e-plan).

    check_commit.py --staged [--json]                     the pre-commit hook's check
    check_commit.py --stage <kind> [<target>] [--json]    stage a Studio commit, write commit-ok.json
    check_commit.py --range <a>..<b> [--record] [--json]  every commit of a range (after an integration)
    check_commit.py --since-last [--record] [--json]      the range from the last checked HEAD

Exit: 0 ok · 1 refused (a check failed) · 2 usage/setup · 3 not supported yet · 4 a person decides
(internal overlay, proxy approvals) · 7 the Studio guard did not run in this Claude Code session.
"""

import json
import os
import sys

from . import checks, kinds, rangecheck, stage
from .gitx import Git, GitError

INV9 = ("Do not bypass this check (--no-verify, HUSKY=0, LEFTHOOK=0, removing session markers): stop and ask the "
        "user (INV9).")
MAX_LIST = 10


def _report(head, problems, warnings=(), stream=None):
    stream = stream or sys.stderr
    seen = set()
    problems = [p for p in problems if not (p.message in seen or seen.add(p.message))]  # one line per reason
    lines = []
    if problems:
        lines.append("%s: refused (%d problem%s)." % (head, len(problems), "" if len(problems) == 1 else "s"))
        for p in problems[:MAX_LIST]:
            lines.append("  - " + p.message)
        if len(problems) > MAX_LIST:
            lines.append("  - …and %d more" % (len(problems) - MAX_LIST))
        lines.append(INV9)
    for w in warnings:
        lines.append("%s: warning: %s" % (head, w))
    if lines:
        stream.write("\n".join(lines) + "\n")


def _json(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv, cwd=None, env=None, extra_kinds=None):
    env = dict(os.environ if env is None else env)
    as_json = "--json" in argv
    args = [a for a in argv if a != "--json"]
    try:
        if not args or args[0] not in ("--staged", "--stage", "--range", "--since-last"):
            raise _Usage(__doc__.strip().splitlines()[0])
        git = Git(cwd or os.getcwd(), env)
        try:
            ctx = checks.Ctx(git, env, kinds.registry(env, extra_kinds))
        except GitError as e:
            raise _Usage("not inside a git work tree (%s)" % e)
        mode = args[0]
        if mode == "--staged":
            if len(args) != 1:
                raise _Usage("--staged takes no arguments")
            code, problems = checks.staged_check(ctx)
            if as_json:
                _json({"ok": code == 0, "code": code, "problems": [_pj(p) for p in problems]})
            else:
                _report("Studio pre-commit", problems)
            return code
        if mode == "--stage":
            if len(args) not in (2, 3):
                raise _Usage("--stage <kind> [<target>]")
            code, problems, data = stage.run(ctx, args[1], args[2] if len(args) == 3 else None)
            if as_json:
                _json({"ok": code == 0, "code": code, "problems": [_pj(p) for p in problems], "commit_ok": data})
            elif code == 0:
                sys.stdout.write("staged %d Studio path%s · tree %s · ask the user with the option \"%s\"\n"
                                 % (len(data["paths"]), "" if len(data["paths"]) == 1 else "s", data["tree"][:12],
                                    data["label"]))
                sys.stdout.write("put this line in the question as it is:\n%s\n" % data["summary"])
                if data.get("values_shown"):
                    if data.get("overflow"):
                        sys.stdout.write("the value block is long: open %s for the person (open it) before asking, "
                                         "then put these lines in the question too:\n" % data["overflow"]["file"])
                    else:
                        sys.stdout.write("and these lines (the protected values, each as it is):\n")
                    for l in data["values_shown"]:
                        sys.stdout.write("%s\n" % l)
                for w in data.get("warnings") or []:
                    sys.stderr.write("Studio stage: warning: %s\n" % w)
                for p in data["paths"][:10]:
                    sys.stdout.write("  %s\n" % p)
                if len(data["paths"]) > 10:
                    sys.stdout.write("  … and %d more\n" % (len(data["paths"]) - 10))
            else:
                _report("Studio stage", problems)
            return code
        record = "--record" in args
        rest = [a for a in args[1:] if a != "--record"]
        if mode == "--range":
            if len(rest) != 1:
                raise _Usage("--range <a>..<b>")
            spec = rest[0]
        else:
            if rest:
                raise _Usage("--since-last takes no range")
            spec = rangecheck.since_last(ctx)
            if spec is None:
                raise _Usage("no last checked HEAD and no upstream to compare with — give --range")
        code, problems, warnings, commits = rangecheck.check(ctx, spec)
        if code == 0 and record:
            rangecheck.record(ctx)
        if as_json:
            _json({"ok": code == 0, "code": code, "range": spec, "problems": [_pj(p) for p in problems],
                   "warnings": warnings, "commits": commits})
        else:
            _report("Studio range check", problems, warnings)
            if code == 0:
                sys.stdout.write("checked %s: %d commit%s\n" % (spec, len(commits), "" if len(commits) == 1 else "s"))
        return code
    except _Usage as e:
        sys.stderr.write("std check_commit: %s\n" % e)
        return 2
    except GitError as e:
        sys.stderr.write("std check_commit: %s\n" % e)
        return 2


def _pj(p):
    d = {"code": p.code, "message": p.message}
    if p.path:
        d["path"] = p.path
    return d


class _Usage(Exception):
    pass
