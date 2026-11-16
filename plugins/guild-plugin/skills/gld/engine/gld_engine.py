#!/usr/bin/env python3
"""gld_engine.py — entry point of the Guild issue-flow engine: `gld_engine.py <workflow> <sub> …`.

    gld_engine.py status show --issue N [--json]       /gld status N as code
    gld_engine.py status route --issue N [--json]      /gld resume N routing
    gld_engine.py status board [section] [--html]      /gld monitoring snapshot
    gld_engine.py status running [--all-repos]         live engine locks (downgrade runbook ①)
    gld_engine.py status directives --open             human directive blocks (runbook ①b)
    gld_engine.py version

Milestone K0: read-only. No command writes GitHub state, spawns a role or calls `claude`; the
`dev` workflow arrives in later milestones. Nothing in the plugin invokes this file yet.

This shim uses only Python 3.6 syntax up to the version check (R6C-m4): an interpreter the
engine cannot run on exits 6 with `halted: env python` before any engine module is imported.
"""

import os
import sys

MIN_PY = (3, 9)


def _halt_python():
    sys.stdout.write("halted: env python\n")
    sys.stderr.write("guild engine needs Python %d.%d+ (found %d.%d)\n"
                     % (MIN_PY[0], MIN_PY[1], sys.version_info[0], sys.version_info[1]))
    return 6


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if sys.version_info[:2] < MIN_PY:
        return _halt_python()
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    if not argv or argv[0] in ("-h", "--help"):
        sys.stdout.write(__doc__.split("\n\n")[1] + "\n")
        return 0 if argv else 64
    wf, rest = argv[0], argv[1:]
    if wf == "version":
        from guildcore import ENGINE_MILESTONE
        sys.stdout.write("guild engine %s\n" % ENGINE_MILESTONE)
        return 0
    if wf == "status":
        from workflows.status import cli
        return cli.main(rest)
    sys.stderr.write("unknown workflow %r — available in this build: status\n" % wf)
    return 64


if __name__ == "__main__":
    sys.exit(main())
