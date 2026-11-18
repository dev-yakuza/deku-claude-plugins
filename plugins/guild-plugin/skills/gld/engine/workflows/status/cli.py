"""workflows.status.cli — `gld_engine.py status <show|route|board|running|directives> …`."""

import argparse
import os
import sys

from guildcore import config as cfgmod
from guildcore import emit, journal
from guildcore.adapters.clock import Clock
from guildcore.adapters.gh import FakeGh, GhCli, GhError
from workflows.status import board, route, running, show


def make_gh(repo=None):
    """A fake GitHub only when BOTH `GLD_ENGINE_TEST=1` and `GLD_ENGINE_GH_FIXTURE=<json>` are
    set (K0-m12 — one stray variable must not make /gld status show a fake repo)."""
    fx = os.environ.get("GLD_ENGINE_GH_FIXTURE")
    if fx and os.environ.get("GLD_ENGINE_TEST") == "1":
        return FakeGh(fx)
    return GhCli(repo)


def own_writes(issue, root="."):
    """The engine's own label-write event ids from this clone's journal (K0-m10) — the same
    input the writer gives `decisions.live`. No git / no journal → none."""
    try:
        return journal.JournalView.read(running.git_common_dir(root), issue).own_label_writes()
    except running.RunningError:
        return []


def parser():
    ap = argparse.ArgumentParser(prog="gld_engine.py status")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("show", "route"):
        p = sub.add_parser(name)
        p.add_argument("--issue", type=int, required=True)
        p.add_argument("--repo")
        p.add_argument("--json", action="store_true")
        p.add_argument("--root", default=".")
    p = sub.add_parser("board")
    p.add_argument("section", nargs="?")
    p.add_argument("--html", action="store_true")
    p.add_argument("--repo")
    p.add_argument("--root", default=".")
    p = sub.add_parser("running")
    p.add_argument("--all-repos", action="store_true")
    p.add_argument("--root", default=".")
    p = sub.add_parser("directives")
    p.add_argument("--open", action="store_true", help="open Issues only (default: all states)")
    p.add_argument("--repo")
    p.add_argument("--all-repos", action="store_true", help="every clone in the config-dir registry (runbook ①b)")
    return ap


def main(argv, out=None, err=None, clock=None, ledger=None):
    out = out or sys.stdout
    err = err or sys.stderr
    a = parser().parse_args(argv)
    if not a.cmd:
        parser().print_usage(err)
        return 64
    try:
        if a.cmd == "show":
            gh = make_gh(a.repo)
            text = show.show(gh, a.issue, own_writes(a.issue, a.root))
            if a.json:
                emit.engine({"issue": a.issue, "text": text}, out)
            else:
                out.write(text)
            return 0
        if a.cmd == "route":
            r = route.route(make_gh(a.repo), a.issue, a.root,
                            unattended=os.environ.get("GLD_UNATTENDED") == "1",
                            own_writes=own_writes(a.issue, a.root))
            if a.json:
                emit.engine(r.as_dict(), out)
            else:
                out.write(r.text())
            return 0 if r.action != "fail" else 1
        if a.cmd == "board":
            cfg = cfgmod.load(a.root)
            invalid = a.section if a.section and a.section not in board.R.SECTIONS else None
            section = None if invalid else a.section
            data = board.gather(a.root, cfg, make_gh(a.repo), section,
                                ledger=ledger or board.run_ledger)
            text = board.render_text(data, cfg.language, (clock or Clock()).now(), section, invalid)
            out.write(text)
            if a.html:
                p = board.html_path(a.root)
                os.makedirs(os.path.dirname(p), exist_ok=True)  # fs-ok: status board html in the engine memory dir (human command)
                with open(p, "w", encoding="utf-8") as fh:  # fs-ok: status board html in the engine memory dir (human command)
                    fh.write(board.render_html(text, board.R.board_text(cfg.language)["title"]))
                out.write("HTML: %s\n" % p)
            return 0
        if a.cmd == "running":
            dirs = running.registry() if a.all_repos else [running.git_common_dir(a.root)]
            halts = []
            rows, missing = running.running(dirs, halts)
            out.write(running.render_running(rows, missing, halts))
            return 0
        if a.cmd == "directives":
            if not a.all_repos:
                out.write(running.render_directives(running.directives(make_gh(a.repo), a.open)))
                return 0
            rows, skipped = [], []
            for d in running.registry():
                repo = running.repo_of(d) if os.path.isdir(d) else None
                if repo is None:
                    skipped.append(d)
                    continue
                rows += running.directives(make_gh(repo), a.open, d)
            text = running.render_directives(rows)
            for d in skipped:
                text += "skipped (registry entry missing or no GitHub origin): %s\n" % d
            out.write(text)
            return 0
    except running.RunningError as e:
        err.write("%s\n" % e)
        return 1
    except cfgmod.ConfigError as e:
        out.write("%s\n" % e)
        return 1
    except GhError as e:
        emit.warn("Issue not readable: %s" % e, err)
        return 1
    return 64
