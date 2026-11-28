"""One channel per repository (readiness T1, user decision R4-14 — design/guild/24-redesign/readiness/promote/t1-guards.md).

A repository uses ONE Guild channel at a time: the stable or the experimental one (SELF / OTHER below). The active one
is written in CHANNEL_FILE at the top of the checkout (one line, a channel name; committed, so every clone and
machine agree).
  - The file names the other channel → every command of this channel is refused (SKILL.md routing asks `channel show`;
    the engine CLI's write commands ask `entry_problem`) and the human is told the switch command.
  - No file → allowed when only this channel's settings exist (or none: a first init writes the file); refused when
    BOTH channels' settings exist (the human chooses with `channel set`).
  - `channel set <channel>` refuses while the channel that is NOT the target has unfinished engine runs of this
    repository on this machine (its records: an Issue not finished, a sprint not ended) and lists them; otherwise it
    writes the file and puts the target channel's commit gate into the pre-commit hook (the shim of init step 6, or the
    `guild-gate` command a hook manager runs — init step 2b — pointed at the target's gate script).
The machine-wide heavy-run lock is not touched (a human rule: one unattended channel at a time — N7 ②).

PROMOTION (T4): the values below are the channel values the promote script swaps. Each line carries its kind:
  `promote: self`    — this channel's value (renamed to the other channel's when the tree is promoted)
  `promote: other`   — the other channel's value (swapped: the promoted tree names this channel there)
  `promote: literal` — the same in both channels, never renamed
"""

import json
import os
import subprocess
import sys

from . import codes, defaults, fsafe, lifecycle, paths as pathsmod, store

CHANNEL_FILE = ".claude/guild-channel"                  # promote: literal — both channels read and write this one file
SELF = "gld"                                           # promote: self
OTHER = "gldx"                                           # promote: other
CHANNELS = (SELF, OTHER)
CONFIG_DIR = {SELF: ".claude/guild",                # promote: self
              OTHER: ".claude/guild-exp"}                   # promote: other  rename-exception: R4-14 channel switch
SETTINGS_FILES = tuple(os.path.basename(f) for f in (defaults.ENGINE_SETTINGS, defaults.HARNESS_SETTINGS))
"""The file names whose presence (never their content — H13) says a channel is set up here."""
ENGINE_HOME = {SELF: (pathsmod.ENV_ENGINE_HOME, pathsmod.DEFAULT_ENGINE_HOME),
               OTHER: ("GX_ENGINE_HOME", "~/.gldx")}    # promote: other — the other channel's engine home (C10, C11)
GATE_SCRIPT = "gates/scripts/gate_precommit.py"         # promote: literal — under CONFIG_DIR[channel]
SHIM = os.path.join("skills", "gld", "gates", "pre-commit.sh")            # promote: self — this plugin's shim
DETECTOR = os.path.join("skills", "gld", "gates", "gate_precommit.py")    # promote: self — init step 2's detector
MANAGED_FILES = ("lefthook.yml", ".lefthook.yml", "lefthook.yaml", ".lefthook.yaml", ".husky/pre-commit",
                 ".pre-commit-config.yaml")             # promote: literal — where init step 2b registers the gate
MANUAL_MANAGERS = ("overcommit", "simple-git-hooks")    # init step 2b: the human registers the command there
TIMEOUT_S = 30

# Readiness T2 (R4-3, R4-13 K2): what each channel does to the files the human's Guild organisation lives in. The
# table is keyed by the channel's NAME, so both rows stay as they are in both trees (literal) and `value` reads the
# row of SELF — in this tree the development channel's, in the promoted tree the stable channel's. Only the stable
# channel writes role files (`.claude/agents/*.md`, init §2) and the shared knowledge (defaults.KNOWLEDGE_DIR).
VALUES = {
    "gldx": {"writes_role_files": False, "writes_knowledge": False},   # promote: literal — the development channel
    "gld": {"writes_role_files": True, "writes_knowledge": True},      # promote: literal — the stable channel
}


def value(name, channel=None):
    """The channel value `name` of `channel` (default: this channel). KeyError for an unknown name (fail-closed)."""
    return VALUES[channel or SELF][name]


def values(channel=None):
    return dict(VALUES[channel or SELF])


class ChannelError(Exception):
    """The switch cannot be made (nothing was written)."""


def _git(top, *args, env=None):
    p = subprocess.run(["git", *args], cwd=top, capture_output=True, text=True, timeout=TIMEOUT_S,
                       env=dict(os.environ if env is None else env, GIT_TERMINAL_PROMPT="0"), stdin=subprocess.DEVNULL)
    return p.returncode, p.stdout.strip()


def top_of(checkout, env=None):
    """The top of the git checkout at `checkout`, or None when it is not one (or not a folder)."""
    if not checkout or not os.path.isdir(checkout):
        return None
    try:
        rc, out = _git(checkout, "rev-parse", "--show-toplevel", env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return os.path.realpath(out) if rc == 0 and out else None


def read_file(top):
    """(value, raw): value = SELF / OTHER, None when there is no file; raw = the text when it names neither."""
    path = os.path.join(top, CHANNEL_FILE)
    try:
        raw = fsafe.read_bytes(path, root=top, max_bytes=256).decode("utf-8", "replace")
    except FileNotFoundError:
        return None, None
    except (fsafe.UnsafePath, OSError, ValueError) as e:
        return None, f"<unreadable: {e}>"
    value = raw.strip()
    return (value, None) if value in CHANNELS else (None, raw.strip()[:40] or "<empty>")


def settings(top):
    """{channel: True when its settings folder holds one of SETTINGS_FILES (the engine's or the commands' settings)}."""
    return {c: any(os.path.isfile(os.path.join(top, CONFIG_DIR[c], f)) for f in SETTINGS_FILES) for c in CHANNELS}


def verdict(checkout, env=None):
    """{allowed, message, top, file, settings, self, other}: may this channel's commands run in `checkout`?"""
    top = top_of(checkout, env)
    out = {"allowed": True, "message": None, "top": top, "file": None, "settings": None, "self": SELF, "other": OTHER,
           "values": values(), "knowledge_dir": defaults.KNOWLEDGE_DIR}
    if top is None:
        out["message"] = "not a git checkout — no channel to check"
        return out
    value, bad = read_file(top)
    out["file"], out["settings"] = value, settings(top)
    if bad is not None:
        out["allowed"] = False
        out["message"] = (f"{CHANNEL_FILE} says {bad!r}, not {SELF} or {OTHER} — choose the channel again: "
                          f"/{SELF} channel {SELF} or /{SELF} channel {OTHER}")
    elif value == OTHER:
        out["allowed"] = False
        out["message"] = (f"this repository's active channel is {OTHER} ({CHANNEL_FILE}) — use /{OTHER}, or switch "
                          f"this repository to {SELF} with /{SELF} channel {SELF}")
    elif value == SELF:
        out["message"] = f"active channel {SELF}"
    elif all(out["settings"].values()):
        out["allowed"] = False
        out["message"] = (f"both channels are set up here ({CONFIG_DIR[SELF]}/ and {CONFIG_DIR[OTHER]}/) and "
                          f"{CHANNEL_FILE} does not say which one is active — choose: /{SELF} channel {SELF} or "
                          f"/{SELF} channel {OTHER}")
    else:
        out["message"] = f"no {CHANNEL_FILE} — only this channel's settings (or none) are here"
    return out


def entry_problem(checkout, env=None):
    """The engine CLI's write commands: None when this channel may act on `checkout`, else the refusal text."""
    v = verdict(checkout, env)
    return None if v["allowed"] else v["message"]


# --- unfinished engine runs of one channel ------------------------------------------------------------------------

def engine_home(channel, environ):
    """The engine home of `channel` on this machine (its own variable, else its default)."""
    var, default = ENGINE_HOME[channel]
    env = dict(environ)
    env[pathsmod.ENV_ENGINE_HOME] = environ.get(var) or default
    return pathsmod.engine_home(env)


def _issue_finished(state):
    """Nothing waits and nothing runs: closed as decided, or every step done / skipped with a pull request."""
    if state.get("closed"):
        return True
    done = (codes.StepStatus.DONE.value, codes.StepStatus.SKIPPED.value)
    return (not state.get("stop") and all(s.get("status") in done for s in state.get("steps") or ())
            and bool((state.get("github") or {}).get("pr_number")))


def unfinished_runs(home, repo):
    """[{kind: issue|sprint, number, why}] of `repo` in the engine home `home` — an Issue that is not finished
    (running, stopped, mid-step, unreadable) and a sprint that has not ended."""
    owner, name = pathsmod.split_repo(repo)
    root = os.path.join(home, "records", owner, name)
    out = []
    try:
        entries = sorted(os.listdir(root))
    except (FileNotFoundError, NotADirectoryError):
        return out
    for e in entries:
        if not e.isdigit():
            continue
        paths = pathsmod.EnginePaths(home, repo, int(e))
        holder = lifecycle.lock_holder(paths)
        try:
            state = store.load_state(paths)
        except (store.CorruptFile, store.FormatMismatch, fsafe.UnsafePath) as x:
            out.append({"kind": "issue", "number": int(e), "why": f"unreadable state ({type(x).__name__})"})
            continue
        if holder is not None and holder.get("issue") == int(e):
            out.append({"kind": "issue", "number": int(e), "why": "running"})
        elif state is not None and not _issue_finished(state):
            stop = state.get("stop") or {}
            why = f"stopped {stop.get('status')} ({stop.get('reason')})" if stop else "not finished"
            out.append({"kind": "issue", "number": int(e), "why": why})
    try:
        trackers = sorted(x for x in os.listdir(os.path.join(root, "sprints")) if x.isdigit())
    except (FileNotFoundError, NotADirectoryError):
        trackers = []
    for t in trackers:
        sp = pathsmod.SprintPaths(home, repo, int(t))
        try:
            sprint = store.load_sprint(sp)
        except (store.CorruptFile, store.FormatMismatch, fsafe.UnsafePath) as x:
            out.append({"kind": "sprint", "number": int(t), "why": f"unreadable sprint record ({type(x).__name__})"})
            continue
        if sprint is not None and sprint.get("state") not in codes.SPRINT_ENDED:
            out.append({"kind": "sprint", "number": int(t), "why": sprint.get("state")})
    return out


# --- the commit gate of the active channel --------------------------------------------------------------------------

def gate_path(channel):
    return f"{CONFIG_DIR[channel]}/{GATE_SCRIPT}"


def shim_text(plugin_root, channel):
    """This plugin's pre-commit shim, pointed at `channel`'s gate script (the shims of the two channels differ only
    in that path — promotion renames one into the other)."""
    with open(os.path.join(plugin_root, SHIM), encoding="utf-8") as f:
        text = f.read()
    mine = gate_path(SELF)
    if mine not in text:
        raise ChannelError(f"the plugin's shim does not name {mine}")
    return text.replace(mine, gate_path(channel))


def _hook_path(top, env=None):
    rc, out = _git(top, "rev-parse", "--path-format=absolute", "--git-path", "hooks/pre-commit", env=env)
    if rc != 0 or not out:
        raise ChannelError("git cannot say where the pre-commit hook lives")
    return out


def detect_manager(plugin_root, hook, top=None):
    """init step 2's detector, run as init runs it: one word (absent · guild · none · a manager name). With no hook
    file, `top`'s committed manager config names the manager (FC M3 — a clone where `lefthook install` never ran)."""
    try:
        p = subprocess.run([sys.executable, "-I", os.path.join(plugin_root, DETECTOR), "--detect-hook-manager", hook,
                            *(["--checkout", top] if top else [])],
                           capture_output=True, text=True, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ChannelError(f"the hook detector did not run: {e}") from None
    word = p.stdout.strip()
    if p.returncode != 0 or not word or " " in word:
        raise ChannelError(f"the hook detector gave no answer (exit {p.returncode}): {p.stderr.strip()[:200]}")
    return word


def plan_hook(top, plugin_root, target, env=None):
    """What the switch does to the commit gate, decided before anything is written:
    {kind, hook, write: [(path, text, mode, root)], move: (src, dst) | None, notes: [..], manual: bool}."""
    hook = _hook_path(top, env)
    word = detect_manager(plugin_root, hook, top)
    plan = {"kind": word, "hook": hook, "write": [], "move": None, "notes": [], "manual": False}
    other = OTHER if target == SELF else SELF
    if word not in ("absent", "guild", "none") and not os.path.lexists(hook):
        plan["notes"].append(f"{word} is configured in this checkout but not installed here (no {hook}) — nothing "
                             f"runs at commit until `{word} install`; no Guild hook is written over it")
    if word in ("absent", "guild", "none"):
        if word == "none":
            local = hook + ".local"
            if os.path.lexists(local):
                plan["manual"] = True
                plan["notes"].append(f"{hook} is a hand-written hook and {local} exists already — nothing moved: put "
                                     f"the {target} gate there by hand (init step 6)")
                return plan
            plan["move"] = (hook, local)
            plan["notes"].append(f"the hand-written hook moves to {local} and still runs first")
        plan["write"].append((hook, shim_text(plugin_root, target), 0o755, os.path.dirname(os.path.dirname(hook))))
        plan["notes"].append(f"pre-commit hook: the {target} gate shim ({gate_path(target)})")
        return plan
    if word in MANUAL_MANAGERS:
        plan["manual"] = True
        plan["notes"].append(f"{word} manages the hook: point its Guild command at "
                             f"`python3 {gate_path(target)} --git-hook` by hand (init step 2b)")
        return plan
    found = False
    for rel in MANAGED_FILES:
        path = os.path.join(top, rel)
        if not os.path.isfile(path) or os.path.islink(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if gate_path(target) in text and gate_path(other) not in text:
            found = True
            plan["notes"].append(f"{rel}: already runs the {target} gate")
        elif gate_path(other) in text:
            found = True
            plan["write"].append((path, text.replace(gate_path(other), gate_path(target)), None, top))
            plan["notes"].append(f"{rel}: the registered gate command now runs {gate_path(target)} (commit it)")
    if not found:
        plan["manual"] = True
        plan["notes"].append(f"{word} manages the hook and no Guild gate command is registered in its config — "
                             f"run /{target} init (step 2b) or /{target} update to register it")
    return plan


def _apply_hook(plan):
    if plan["move"]:
        os.rename(*plan["move"])
    for path, text, mode, root in plan["write"]:
        old = os.stat(path).st_mode & 0o777 if mode is None and os.path.exists(path) else None
        fsafe.write_text(path, text, root=root, mode=mode if mode is not None else (old or 0o644))


# --- the switch -----------------------------------------------------------------------------------------------------

def switch(target, repo, checkout, environ, plugin_root, dry_run=False):
    """`engine.py channel set <target>`: {done, refused, file_before, unfinished, hook, notes}. Raises ChannelError
    when the switch cannot even be judged (no checkout, no hook answer). Nothing is written on a refusal."""
    if target not in CHANNELS:
        raise ChannelError(f"unknown channel {target!r} (choose {SELF} or {OTHER})")
    top = top_of(checkout, environ)
    if top is None:
        raise ChannelError(f"{checkout} is not a git checkout")
    pathsmod.split_repo(repo)
    before, bad = read_file(top)
    other = OTHER if target == SELF else SELF
    home = engine_home(other, environ)
    rep = {"target": target, "top": top, "file_before": before if bad is None else bad, "done": False,
           "refused": None, "unfinished": unfinished_runs(home, repo), "other_home": home, "hook": None, "notes": []}
    if rep["unfinished"]:
        listed = ", ".join(f"{'sprint ' if u['kind'] == 'sprint' else ''}#{u['number']} ({u['why']})"
                           for u in rep["unfinished"])
        rep["refused"] = (f"the {other} channel still has engine runs of {repo} on this machine ({home}): {listed} — "
                          f"finish them (or stop them) with /{other} first; nothing was changed")
        return rep
    plan = plan_hook(top, plugin_root, target, environ)
    rep["hook"] = {k: plan[k] for k in ("kind", "hook", "manual")}
    rep["notes"] += plan["notes"]
    if not os.path.isfile(os.path.join(top, gate_path(target))):
        rep["notes"].append(f"{gate_path(target)} is not in this checkout — the hook has no gate to run until "
                            f"/{target} init or /{target} update puts it there")
    rc, hooks_path = _git(top, "config", "--get", "core.hooksPath", env=environ)
    if rc == 0 and hooks_path and plan["kind"] in ("absent", "guild", "none"):
        rep["notes"].append(f"core.hooksPath is {hooks_path}: git does not run {plan['hook']} (init step 5)")
    rc, _ = _git(top, "check-ignore", "-q", CHANNEL_FILE, env=environ)
    ignored = rc == 0
    rep["gitignore"] = None
    if ignored and dry_run:
        rep["notes"].append(f"{CHANNEL_FILE} is ignored by git here — the switch adds `!{CHANNEL_FILE}` to .gitignore "
                            "so the choice is committed with the repository")
    if dry_run:
        return rep
    fsafe.write_text(os.path.join(top, CHANNEL_FILE), target + "\n", root=top, mode=0o644)
    _apply_hook(plan)
    if ignored:
        rep["gitignore"], note = unignore_channel_file(top, environ)
        rep["notes"].append(note)
    rep["done"] = True
    return rep


def unignore_channel_file(top, environ=None):
    """FC M4: the repository's .gitignore hides CHANNEL_FILE (app_a: `.claude/*`) — append `!CHANNEL_FILE` to the
    top .gitignore, then ask git again. Still ignored (git cannot re-include a file whose parent folder is ignored
    as a whole, e.g. `.claude/`; or a deeper .gitignore wins) → the .gitignore is put back as it was and the human
    is told what to change. Returns ("added" | "kept", note)."""
    path = os.path.join(top, ".gitignore")
    try:
        old = fsafe.read_bytes(path, root=top, max_bytes=4 << 20)
    except FileNotFoundError:
        old = None
    except (fsafe.UnsafePath, OSError) as e:
        return "kept", (f"{CHANNEL_FILE} is ignored by git here and .gitignore cannot be changed safely ({e}) — add "
                        f"`!{CHANNEL_FILE}` to .gitignore by hand so the choice is committed")
    line = f"!{CHANNEL_FILE}\n".encode()
    new = (old or b"") + (b"\n" if old and not old.endswith(b"\n") else b"") + line
    fsafe.write_bytes(path, new, root=top)
    rc, _ = _git(top, "check-ignore", "-q", CHANNEL_FILE, env=environ)
    if rc != 0:
        return "added", (f"{CHANNEL_FILE} was ignored by git here — added `!{CHANNEL_FILE}` to .gitignore; commit "
                         ".gitignore with it")
    if old is None:
        os.unlink(path)
    else:
        fsafe.write_bytes(path, old, root=top)
    return "kept", (f"{CHANNEL_FILE} is ignored by git here and `!{CHANNEL_FILE}` in .gitignore does not bring it back "
                    "(a parent folder is ignored as a whole, e.g. `.claude/`, or a deeper .gitignore hides it) — "
                    f".gitignore is unchanged: ignore `.claude/*` instead of `.claude/` and add `!{CHANNEL_FILE}` by hand")


def format_switch(rep):
    lines = []
    if rep["refused"]:
        return f"refused: {rep['refused']}\n"
    head = "would switch" if not rep["done"] else "switched"
    lines.append(f"{head}: {CHANNEL_FILE} {rep['file_before'] or '(none)'} -> {rep['target']}")
    lines += [f"- {n}" for n in rep["notes"]]
    if rep["done"]:
        extra = " and .gitignore" if rep.get("gitignore") == "added" else ""
        lines.append(f"- commit {CHANNEL_FILE}{extra} (and a changed hook config) so every clone uses {rep['target']}")
    return "\n".join(lines) + "\n"


def format_show(v):
    return ("allowed" if v["allowed"] else "refused") + f": {v['message']}\n"


def show_json(v):
    return json.dumps(v, ensure_ascii=False, indent=2) + "\n"
