"""hooks.py — Studio's pre-commit hook (M0e; m0e-plan §3).

    hooks.py install [--husky-apply] [--json]
    hooks.py status [--json]

Exit: 0 installed / valid · 1 cannot install (or invalid, for status) · 2 usage/setup · 4 a person decides
(a block proposed for a file shared with the team).
"""

import json
import os
import sys

from ..commit.gitx import Git, GitError
from ..commit.spaths import read_config
from . import install as I


def main(argv, cwd=None, env=None):
    env = dict(os.environ if env is None else env)
    as_json = "--json" in argv
    args = [a for a in argv if a != "--json"]
    try:
        if not args or args[0] not in ("install", "status"):
            raise _Usage(__doc__.strip().splitlines()[0])
        git = Git(cwd or os.getcwd(), env)
        try:
            top = git.toplevel()
        except GitError as e:
            raise _Usage("not inside a git work tree (%s)" % e)
        git.cwd = top
        cfg, err = read_config(top)
        if cfg is None:
            raise _Usage(err or "no Studio harness here (.claude/studio/config.json is missing)")
        if args[0] == "status":
            if len(args) != 1:
                raise _Usage("status takes no arguments")
            st = I.status(git, top, env)
            if as_json:
                sys.stdout.write(json.dumps(st, ensure_ascii=False, sort_keys=True) + "\n")
            else:
                sys.stdout.write("Studio hook (%s): %s\n" % (st["manager"], "valid" if st["valid"] else "NOT valid"))
                for r in st["reasons"]:
                    sys.stdout.write("  - %s\n" % r)
            return 0 if st["valid"] else 1
        extra = [a for a in args[1:] if a != "--husky-apply"]
        if extra:
            raise _Usage("unknown argument: %s" % extra[0])
        res = I.install(git, top, env, husky_apply="--husky-apply" in args)
        if as_json:
            sys.stdout.write(json.dumps(res.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        else:
            out = sys.stdout if res.code == 0 else sys.stderr
            out.write("Studio hook (%s): %s\n" % (res.manager, "wrote %d file(s)" % len(res.wrote) if res.wrote
                                                  else "up to date"))
            for p in res.wrote:
                out.write("  wrote %s\n" % p)
            for p in res.problems:
                out.write("  problem: %s\n" % p)
            for w in res.warnings:
                out.write("  note: %s\n" % w)
            if res.proposal:
                out.write("  proposed block:\n" + "".join("    " + l for l in res.proposal.splitlines(True)))
        return res.code
    except _Usage as e:
        sys.stderr.write("std hooks: %s\n" % e)
        return 2
    except (GitError, OSError) as e:
        sys.stderr.write("std hooks: %s\n" % e)
        return 2


class _Usage(Exception):
    pass
