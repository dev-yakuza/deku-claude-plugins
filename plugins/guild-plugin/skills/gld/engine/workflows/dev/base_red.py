"""workflows.dev.base_red — a red suite's failures that are red on the base too (0.102.16, lead decision 3).

one-man-company #687 (0.102.14): 21 failures in test/tool/* came from the engine's environment (a temp tree without
`.git`, test helpers that strip GIT_* under a sandbox that denies ~/.gitconfig), none from the change. The developer
was sent back twice for them and the execute cap stopped the run as "suite red" — and every resume would repeat it.

The rule (deterministic, file-level, one base re-run per suite):
* only a red, finished run (no timeout, every command ran) whose counted failures the engine can ALL name with their
  test file (flutter / dart `<path>: <name> [E]` lines, pytest `FAILED <path>::<name>`; the summary's failed count
  equals the named failures) — otherwise nothing is excluded;
* the failing test files that are UNCHANGED against the base (not in `diff base..HEAD`, not modified / added /
  deleted in the worktree) are re-run ONCE, together, on the base: the suite's own temp tree with the change's files
  put back to the base (the tree was warmed at the base — only when the change's build inputs are `none`), its own
  git repo re-made from the base's files, the same sandbox / env / shims;
* a failure is PRE-EXISTING in the engine env iff its file is unchanged AND the same test (file + name) is red on the
  base; it is left out of the verdict, recorded as a decision block (`point: base-red`, `grade: trigger` — a
  grading-sheet row) and a journal event — never a developer loop-back or a person's stop. Every other failure is
  NEW: it alone counts and alone goes into the retry note.
* the conservative switch: config `engine.base_red: false`, or a confirmed `wrong` on a base-red row
  (`group.base-red.conservative`, like the flake valve) — then a red suite stays red as it is.
"""

import os
import re
import shlex
import shutil

from guildcore import checks as CH
from guildcore import fsafe as FS
from guildcore.adapters import git as G

POINT = "base-red"
GROUP = "base-red"
VALVE = "group.base-red.conservative"
RUNNERS = ("flutter", "dart", "pytest")
_FLUTTER_NAME = re.compile(r"^(?:loading (?P<load>.+?\.dart)|(?P<path>.+?\.dart): (?P<name>.*))$")


def enabled(cfg):
    """config `engine.base_red` — on unless it is literally false."""
    raw = getattr(cfg, "raw", None) or (cfg if isinstance(cfg, dict) else {})
    return (raw.get("engine") or {}).get("base_red", True) is not False


def off(p, cfg=None):
    """The conservative switch: the config turns it off, or a confirmed wrong set the valve."""
    from workflows.dev import predict as PF
    if cfg is not None and not enabled(cfg):
        return True
    return bool(PF._truthy((getattr(p, "valves", None) or {}).get(VALVE)))


def _rel(path, prefixes):
    path = (path or "").strip()
    if os.path.isabs(path):
        for pre in prefixes:
            pre = (pre or "").rstrip("/")
            if pre and path.startswith(pre + "/"):
                path = path[len(pre) + 1:]
                break
        else:
            return None
    rel = os.path.normpath(path)
    if rel.startswith("..") or os.path.isabs(rel) or rel == ".":
        return None
    return rel


def failures(raw, prefixes=(), config=None):
    """(runner, [(file, name)]) for EVERY failure the run counts, or (runner, None) when one of them cannot be named
    with its file (or the format is unknown). A green / unreadable run → (runner|None, None)."""
    summ = CH.parse_summary(raw, config=config)
    if summ is None or summ.runner not in RUNNERS or summ.failed <= 0:
        return (summ.runner if summ else None), None
    names = list(summ.failed_names)
    if len(names) != summ.failed:
        return summ.runner, None
    out = []
    for n in names:
        if summ.runner == "pytest":
            path, sep, name = n.partition("::")
            if not sep or not path.endswith(".py"):
                return summ.runner, None
        else:
            m = _FLUTTER_NAME.match(n.strip())
            if not m:
                return summ.runner, None
            path, name = (m.group("load"), "(loading)") if m.group("load") else (m.group("path"), m.group("name"))
        rel = _rel(path, prefixes)
        if rel is None:
            return summ.runner, None
        out.append((rel, name))
    return summ.runner, out


def changed_paths(root, base):
    """Every path the change touches against `base`: committed (`diff base..HEAD`) and uncommitted (modified, added,
    deleted in the worktree)."""
    out = set()
    for args in (("diff", "--name-only", "-z", "--no-renames", base, "HEAD"),
                 ("ls-files", "-z", "-m", "-o", "--exclude-standard"), ("ls-files", "-z", "-d")):
        out.update(x for x in G.run(root, *args).decode("utf-8", "replace").split("\0") if x)
    return sorted(os.path.normpath(x) for x in out)


def base_command(runner, files, cmds=(), env=None):
    """ONE command that runs exactly `files` with the runner's text reporter (the names come back the same way)."""
    q = " ".join(shlex.quote(f) for f in files)
    if runner == "flutter":
        path = (env or {}).get("PATH") or os.environ.get("PATH", "")
        exe = "flutter" if shutil.which("flutter", path=path) or not shutil.which("fvm", path=path) else "fvm flutter"
        return "%s test --no-pub -r expanded %s" % (exe, q)
    if runner == "dart":
        return "dart test -r expanded %s" % q
    if runner == "pytest":
        from workflows.dev import flake as FL
        interp = next((m.group(1) for m in (FL.INTERP_RE.search(c or "") for c in cmds or ()) if m), None)
        return "%s -m pytest -v -rs %s" % (interp or "python3", q)
    return None


def check(r, cmds, root, base, tt, run, prefixes, config=None, env=None):
    """The rule (module doc) for one finished red suite result `r` of `cmds` in temp tree `tt` (warmed at `base`).
    `run(cmd)` runs one command in the suite's own tree / sandbox / env. Returns the note
    {runner, failures, changed, files, cmd, base_rc, base_summary, excluded, new} or None (not eligible: nothing is
    excluded). The tree is left at the base — call it LAST."""
    if r is None or r.passed or r.timed_out or not base:
        return None
    if len(getattr(r, "steps", None) or []) != len(cmds or ()):
        return None                                     # a later command never ran: its failures are unknown
    runner, fails = failures(r.raw, prefixes, config)
    if not fails:
        return None
    try:
        changed = set(changed_paths(root, base))
    except G.GitError:
        return None
    files = sorted(set(f for f, _n in fails if f not in changed))
    note = {"runner": runner, "failures": ["%s: %s" % x for x in fails],
            "changed": sorted(set(f for f, _n in fails if f in changed)), "files": files, "cmd": None,
            "base_rc": None, "base_summary": None, "excluded": [], "new": ["%s: %s" % x for x in fails]}
    if not files:
        return note
    cmd = base_command(runner, files, cmds, env)
    if not cmd:
        return note
    try:
        tt.to_base(sorted(changed))
    except (ValueError, OSError, G.GitError, FS.UnsafePath):
        return note
    tt.make_git(rev=base)
    res = run(cmd)
    note["cmd"], note["base_rc"] = cmd, getattr(res, "rc", None)
    if res is None or res.timed_out:
        return note
    summ = CH.parse_summary(res.raw)
    note["base_summary"] = summ.as_dict() if summ else None
    if summ is None:
        return note                                     # the base run is unreadable — nothing is excluded
    _rn, base_fails = failures(res.raw, prefixes)
    red = set(base_fails or ())
    keep = [x for x in fails if not (x[0] in files and x in red)]
    note["excluded"] = ["%s: %s" % x for x in fails if x[0] in files and x in red]
    note["new"] = ["%s: %s" % x for x in keep]
    return note


def line(note):
    """The one evidence / log line of the excluded failures."""
    ex = note.get("excluded") or []
    files = sorted(set(x.split(": ", 1)[0] for x in ex))
    return "red on the base too (pre-existing in the engine env, left out): %d failure(s) in %s" % (
        len(ex), ", ".join(files[:6]) + (" …" if len(files) > 6 else ""))


def red_reason(note):
    """The retry note's reason: the NEW failures only."""
    new = note.get("new") or []
    return "suite red — new failure(s) (not red on the base, or in a changed test file): %s%s; %s" % (
        "; ".join(new[:5]), " …(+%d)" % (len(new) - 5) if len(new) > 5 else "", line(note))


def record(p, stage, note):
    """A decision block (`point: base-red`, `grade: trigger` — a grading-sheet row of its own) and a journal event."""
    from workflows.dev.stages import base as B
    files = sorted(set(x.split(": ", 1)[0] for x in note.get("excluded") or []))
    B.record_code(p, stage, POINT, "excluded", refs=",".join(files)[:200],
                  reason=B.one_line("%s — new: %d" % (line(note), len(note.get("new") or [])), 300),
                  extra={"grade": "trigger"})
    j = getattr(p, "journal", None)
    if j is not None:
        j.append("event", what="base-red", stage=stage, excluded=note.get("excluded") or [],
                 new=note.get("new") or [], cmd=note.get("cmd"))
