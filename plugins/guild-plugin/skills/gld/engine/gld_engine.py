#!/usr/bin/env python3
"""gld_engine.py — entry point of the Guild issue-flow engine: `gld_engine.py <workflow> <sub> …`.

    gld_engine.py status show --issue N [--json]       /gld status N as code
    gld_engine.py status route --issue N [--json]      /gld resume N routing
    gld_engine.py status board [section] [--html]      /gld monitoring snapshot
    gld_engine.py status running [--all-repos]         live engine locks (downgrade runbook ①)
    gld_engine.py status directives --open             human directive blocks (runbook ①b)
    gld_engine.py dev run --issue N [--attended|--unattended] [--detach] [--only STAGE]
    gld_engine.py dev wait|answer|note|hold …          the attended driver's channel (dev.md)
    gld_engine.py dev valve set|clear|halt|resume|show soft valves and the kill switch (§10.5)
    gld_engine.py dev cost|health|grade|unattended-log measurement and records
    gld_engine.py version

K5: the `dev` workflow (workflows/dev/cli.py) — the attended driver (commands/dev.md), the supervisor
and batch call it (§2.4).

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
        if rest[:1] == ["--active"]:
            # §10.3: the ACTIVE plugin version for the supervisor's per-pass check — one line:
            # `<version>` | `count:<n>` (not exactly one enabled guild-plugin) | `unavailable`
            from guildcore import version as V
            cwd = rest[rest.index("--cwd") + 1] if "--cwd" in rest[:-1] else os.getcwd()
            try:
                vers = V.active(cwd)
            except Exception:                                   # noqa: BLE001 — a check that cannot run
                try:
                    import time
                    time.sleep(5)
                    vers = V.active(cwd)
                except Exception:                               # noqa: BLE001
                    sys.stdout.write("unavailable\n")
                    return 0
            sys.stdout.write((vers[0] if len(vers) == 1 else "count:%d" % len(vers)) + "\n")
            return 0
        from guildcore import ENGINE_MILESTONE
        sys.stdout.write("guild engine %s\n" % ENGINE_MILESTONE)
        return 0
    if wf == "status":
        from workflows.status import cli
        return cli.main(rest)
    if wf == "dev":
        from workflows.dev import cli as dev_cli
        return dev_cli.main(rest)
    sys.stderr.write("unknown workflow %r — available in this build: status, dev\n" % wf)
    return 64


if __name__ == "__main__":
    sys.exit(main())
