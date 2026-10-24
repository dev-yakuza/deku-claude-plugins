"""setup.py — install and maintain Studio's harness (m1-plan §5). Plugin-only (never copied into a repository).

    setup.py init analyze [--studio-root R]                       drafts for the interview (read-only)
    setup.py init plan --answers <json file> [--out <file>]       what init will write (no writes but the plan)
    setup.py init apply [--plan <file>]                           write the harness (no evidence: the first harness
                                                                  commit is the person's check)
    setup.py config get [<key>]
    setup.py config preview <key> <value>                         the label and line of a protected change
    setup.py config set <key> <value> [--expect <h12>]            protected keys and s2v.path: 설정 <h12>
    setup.py narrator preview <lang> --engine qwen:<X> --style <s> [--id narrator]
    setup.py narrator set <lang> --engine qwen:<X> --style <s> [--id narrator] --expect <h12>      설정 <h12>
    setup.py update plan [--take <path>=new|local,…]
    setup.py update apply --expect <h12> [--take …]               갱신 <h12>

Output: JSON on stdout. Exit: 0 ok · 1 refused (a check failed) · 2 usage/setup (no harness: everything but init) ·
3 refused (a harness exists, a conflict, a video in progress) · 6 no evidence of the person's answer."""

import json
import os
import sys

from . import analyze, configcmd, initcmd, update
from .common import USAGE, SetupError, toplevel


def _opts(rest, values, flags=("--proxy",)):
    out = {"_": []}
    it = iter(rest)
    for a in it:
        if a.startswith("--") and "=" in a:
            k, v = a.split("=", 1)
            if k not in values:
                raise SetupError(USAGE, "unknown option: %s" % k)
            out[k] = v
        elif a in flags:
            out[a] = True
        elif a in values:
            v = next(it, None)
            if v is None:
                raise SetupError(USAGE, "%s needs a value" % a)
            out[a] = v
        elif a.startswith("--"):
            raise SetupError(USAGE, "unknown option: %s" % a)
        else:
            out["_"].append(a)
    return out


def _print(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def _load(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        raise SetupError(USAGE, "cannot read the %s %s (%s)" % (what, path, e.strerror))
    except ValueError as e:
        raise SetupError(USAGE, "the %s %s is not JSON (%s)" % (what, path, e))


def main(argv, cwd=None, env=None, version=None):
    env = dict(os.environ if env is None else env)
    try:
        if len(argv) < 2:
            raise SetupError(USAGE, __doc__.strip().splitlines()[0])
        group, sub, rest = argv[0], argv[1], argv[2:]
        top = toplevel(cwd or os.getcwd())
        if group == "init":
            if sub == "analyze":
                o = _opts(rest, ("--studio-root",))
                from ..commit.gitx import Git
                from .. import paths
                g = Git(top, paths.git_env(env))
                _print(analyze.analyze(top, g, o.get("--studio-root") or "studio"))
                return 0
            if sub == "plan":
                o = _opts(rest, ("--answers", "--out"))
                if not o.get("--answers"):
                    raise SetupError(USAGE, "init plan needs --answers <json file>")
                p = initcmd.plan(top, _load(o["--answers"], "answers"), version=version)
                out = o.get("--out") or initcmd.plan_path(top)
                os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(p, f, ensure_ascii=False, indent=2, sort_keys=True)
                _print({"plan": out, "sha": p["sha"], "answers": p["answers"], "s2v": p["s2v"],
                        "files": sorted(p["files"]), "scripts": len(p["scripts"]), "local": p["local"],
                        "hooks": p["hooks"],
                        "replaces": ["%s — exists, will be replaced" % r for r in p["replaces"]]})
                return 0
            if sub == "apply":
                o = _opts(rest, ("--plan",))
                _print(initcmd.apply(top, _load(o.get("--plan") or initcmd.plan_path(top), "plan"), env=env,
                                     version=version))
                return 0
        if group == "config":
            if sub == "get":
                o = _opts(rest, ())
                _print({"value": configcmd.get(top, o["_"][0] if o["_"] else None)})
                return 0
            if sub in ("preview", "set"):
                o = _opts(rest, ("--expect",))
                if len(o["_"]) != 2:
                    raise SetupError(USAGE, "config %s <key> <value>" % sub)
                if sub == "preview":
                    _print(configcmd.preview(top, *o["_"]))
                    return 0
                _print(configcmd.set_(top, o["_"][0], o["_"][1], o.get("--expect"), list(argv),
                                      proxy=bool(o.get("--proxy"))))
                return 0
        if group == "narrator" and sub in ("preview", "set"):
            o = _opts(rest, ("--engine", "--style", "--id", "--expect"))
            if len(o["_"]) != 1 or not o.get("--engine") or "--style" not in o:
                raise SetupError(USAGE, "narrator %s <lang> --engine qwen:<speaker> --style <text> [--id narrator]"
                                 % sub)
            nid = o.get("--id") or "narrator"
            if sub == "preview":
                p = configcmd.narrator_preview(top, o["_"][0], o["--engine"], o["--style"], nid)
                p.pop("status", None)
                _print(p)
                return 0
            _print(configcmd.narrator_set(top, o["_"][0], o["--engine"], o["--style"], o.get("--expect"),
                                          list(argv), nid, proxy=bool(o.get("--proxy"))))
            return 0
        if group == "update" and sub in ("plan", "apply"):
            o = _opts(rest, ("--take", "--expect"))
            if o["_"]:
                raise SetupError(USAGE, "update %s takes no positional arguments" % sub)
            if sub == "plan":
                _print(update.public(update.plan(top, o.get("--take"))))
                return 0
            _print(update.apply(top, o.get("--expect"), o.get("--take"), list(argv), proxy=bool(o.get("--proxy"))))
            return 0
        raise SetupError(USAGE, "unknown command: setup.py %s %s" % (group, sub))
    except SetupError as e:
        sys.stderr.write("std setup: %s\n" % e)
        return e.code


def entry():
    from .. import writes
    writes.enable()  # setup.py writes machine.json, the used-answer record and the harness (M1b review Y2)
    return main(sys.argv[1:])
